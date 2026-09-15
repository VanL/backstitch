# Deterministic-Enough Semantic Gate Spec

Status: Active

Related coverage behavior: `docs/specs/08-intent-coverage.md` [COV-7],
[COV-8], [COV-9].

## 1. Purpose And Scope [SEM-1]

Backstitch semantic analysis is a bounded search heuristic over deterministic
packets. It may become a CI gate only when the stochastic search is separated
from deterministic replay, evidence, policy, and exit behavior.

This spec defines:

- inference-affecting fingerprints and immutable verdict caching
- replayable evidence and result provenance
- semantic diagnostic identity and policy projection
- packaged default policy versus repository-applied policy
- completeness and exit-code rules
- a measured mutation/negative-control evaluation lane
- Backstitch's first repository dogfood gate

It does not claim that a model proves semantic entailment. A result can be
evidence-bound and replayable without being mechanically true.

_Implementation mapping_:

- `backstitch/semantic_analysis.py`
- `backstitch/semantic_application.py`

## 2. Mental Model And Layering [SEM-2]

The semantic path is:

```text
deterministic packet
  -> inference fingerprint
  -> validated untrusted immutable cache lookup
  -> controlled model search on a miss
  -> canonical evidence-bound result
  -> semantic diagnostic identity
  -> packaged default policy
  -> repository-applied policy
  -> fail_on
  -> exit 0 / 1 / 2
```

These layers are distinct contracts:

- Classification is a policy-neutral model result.
- Verification state says what independent support exists for that result.
- Diagnostic identity is stable machine vocabulary derived from classification
  and verification state.
- Default severity comes from packaged defaults.
- Effective severity comes from the merged repository policy.
- `fail_on` determines whether effective findings exit `1`.

Policy, rendering, concurrency, output location, and suppressions never alter a
raw-verdict cache key. Changing policy must re-evaluate cached verdicts with zero
provider calls.

A valid governed suppression may create a `suppression` obligation and
packet. The declaration rationale, normalized operational rules, complete
matched suppression decisions, and bounded issue-source excerpts are
model-visible evidence and therefore affect that suppression packet's hash.
Adding the suppression packet kind or replaying an unchanged deterministic
decision does not by itself alter a section or invariant packet. A rule,
scope, code, source, mapping, matched-finding, or meta-classification change
that changes an existing packet's model-visible issues or evidence honestly
changes that packet's identity. A meta/rung change may add or remove an
eligible packet without changing an otherwise identical projection. Policy,
dispositions, rendering,
and audit display remain outside every raw-verdict cache key.

The raw-result cache is an optimization, not evidence authority. Every current
invocation derives a fresh source snapshot and packet set and validates every
reused object against the complete inference identity. Every invocation that
reaches publication regenerates policy-neutral result JSONL plus the
operational report. A failure before report publication remains an explicit
error and log event; no report is fabricated. Cached raw results may survive
across runs; a prior run report is never an input to a later run.

_Implementation mapping_:

- `backstitch/semantic_analysis.py`
- `backstitch/semantic_policy.py`

### 3. Packet And Inference Identity [SEM-3]

Current section and invariant packet rows retain schema 3 exactly.
Opted-in suppression packet rows use schema 4. A current packet artifact may
contain both versions; version is determined per row, never inferred from
position or kind. Their closed artifact shape, exact model-visible projection,
receipt identity, evidence universe, ordering, byte ceilings, and packet-hash
preimage are [EVC-9.1].

```text
{
  schema_version: 4,
  packet_id, packet_hash,
  kind: "suppression",
  obligation_id,
  source_snapshot: {
    snapshot_hash, obligation_state_hash, derivation_config_hash
  },
  readiness: {
    intent_state, alignment_state, disposition, obligation_rung, gate_state,
    required_roles
  },
  requirement,
  suppression_rules,
  counterevidence,
  evidence_regions,
  issues,
  packet_warnings
}
```

One executable schema-4 packet is emitted per referenced declaration,
grouping every matched decision that names it in canonical rule/issue order.
`packet_id` and `obligation_id` are both
`suppression::PATH#SUP-ID`. Readiness is exactly `identified`, `complete`,
`evaluate`, `active`, `executable`, with `required_roles = []`.
`requirement` uses the schema-3 requirement shape: role `requirement`, the
declaration's spec path, identity `SUP-ID`, owning section title, exact
marker start/end coordinates, and decoded rationale as text.

`suppression_rules` is a nonempty canonical array with exactly:

```text
{
  mechanism: "ignore" | "meta",
  provenance:
    "meta" | "config_file" | "config_section" |
    "inline_spec" | "inline_code",
  path,
  sections,
  codes,
  declaration,
  origin: {
    source, position, line
  }
}
```

`sections` and `codes` are the normalized arrays from [EXC-6].
`declaration` equals the packet declaration reference. `origin.source` is
the exact config-layer or repository-relative source path;
`origin.position` is the zero-based structured-config array position or null;
`origin.line` is the positive inline source line or null. Exactly one of
position/line is non-null. Legacy rules cannot produce suppression packets
because they have no declaration.

`issues` is the complete nonempty canonical [SC-6] projection of matched
suppressed issues. For each issue with a source path and positive line,
`counterevidence` contains the exact single LF-delimited logical source line
from the accepted snapshot in this closed shape:

```text
{
  role: "counterevidence",
  path, start_line, end_line, snippet,
  issue_indexes
}
```

`issue_indexes` is the sorted, unique, nonempty array of zero-based indexes
into `issues` whose locators share that exact path and line. Equal source
lines merge; disjoint lines remain separate.
Issues without such a locator remain in `issues` and produce no invented
region. `evidence_regions` contains the requirement and those
counterevidence regions in [SEM-5] order. `packet_warnings` is exactly `[]`.
Empty, sampled, or truncated rule/issue populations are invalid and overflow
is fatal under existing packet byte ceilings.

The schema-4 model-visible projection is exactly:

```text
{
  packet_contract_version: 4,
  packet_id, kind, obligation_id,
  requirement,
  suppression_rules,
  counterevidence,
  evidence_regions,
  issues,
  packet_warnings
}
```

`packet_hash` is SHA-256 of canonical JSON for that projection. Source
snapshot, readiness, policy, audit rendering, and provenance outside
`suppression_rules.origin` are excluded.

Suppression packets use packet schema 4 and a code-owned suppression prompt.
Section and invariant schema, projection, prompt descriptor, packet hash,
result schema, and analysis-key construction remain byte-for-byte unchanged.
New readers accept the exact mixed population and the prior
section/invariant-only population.

Standalone `packets --kind` accepts `suppression`; `all` includes it.
`check`, `packets`, and obligation commands remain deterministic and do not
import `llm`.

Schema-3 `packet_warnings` is a compatibility field and is exactly `[]`.
Current packet generation and loading reject nonempty schema-3 warnings:
required text or universe budget overflow is fatal under [EVC-9.1], never a
warning-based truncation. The analyzer exposes no `packet_warnings` policy
setting. Every schema-3 analysis report has `packet_warning_count = 0` and
`packet_warning_debt = []`, regardless of current or historical scope.

The following schema-2 projection vocabulary is retained only to validate and
render bounded historical artifacts. It is never produced, prompted, cached,
upgraded, or accepted by a current or qualification run:

- section: `packet_id`, `kind`, `spec_path`, `section_id`, `title`,
  `section_text`, `section_start_line`, derived `section_end_line`, `owners`,
  `tests`, `issues`, `packet_warnings`, and derived `evidence_regions`
- invariant: `packet_id`, `kind`, `invariant_id`, `tier`, `statement`,
  `declaration`, `targets`, `binding_tests`, `issues`, `packet_warnings`, and
  derived `evidence_regions`

`schema_version`, `instructions`, `packet_hash`, invariant `content_hash`,
unknown input extensions, provenance, and cache metadata are excluded. Unknown
packet keys remain tolerated under [SC-13.1], but they are never model-visible,
never hashed, and never stored in the canonical packet cache object. The
nested projection records are closed and have these exact shapes:

- each model-visible `owners`, `targets`, or `binding_tests` item has `path`,
  nullable `symbol`, `start_line`, derived nullable `end_line`, and `snippet`;
  `end_line` is null exactly when the snippet has no lines
- each section `tests` item is a nonblank path string
- each invariant `declaration` has `kind`, `path`, `line`, nullable `symbol`,
  nullable `section_id`, `start_line`, `end_line`, and `excerpt`; exactly one
  owner locator is non-null as required by [INV-5]
- each semantic `issues` item has exactly `code`, `path`, `line`, `message`,
  `section_id`, `symbol`, `short_code`, `context`, `default_severity`, and
  `invariant_id`, with the types and relationships required by [SC-6]; the
  repository-effective deterministic `severity` is deliberately excluded
- each `packet_warnings` item is a string
- each `evidence_regions` item has exactly `role`, `path`, `start_line`, and
  `end_line`; it is derived from a nonblank shown requirement, implementation,
  or test region and is the closed coordinate vocabulary supplied to the model

The existing [SC-6] locator, ordering, cap, and vocabulary rules apply. The
new declaration span is inclusive, contains `line`, and its excerpt is the
exact newline-joined packet text for that span. No nested extension is copied
into the projection. When one nonblank snippet is fully contained in another
snippet with the same path and role, only the first maximal snippet remains
model-visible; equal later duplicates are also omitted. Partial or disjoint
ranges remain separate. This removes redundant coordinate choices without
hiding any shown line. Derived end lines and evidence regions enter
`packet_hash` through the projection.

V2 packets do not carry instructions. Legacy packet `instructions` are ignored
during normalization. The code-owned prompt is selected only by packet kind,
so hostile packet bytes cannot change instructions without changing the keyed
prompt descriptor.

The historical `packet_hash` was lowercase SHA-256 of canonical JSON for that projection:
`json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=True)` encoded
as UTF-8. Current requests instead use the exact [EVC-9.1] projection: prompt
instruction bytes, two newline bytes, then its canonical JSON. Derived hashes,
snapshot/readiness metadata, provenance, gold labels, policy, and cache
metadata never enter the request.

Each prompt has a code-owned nonblank ID, positive integer version, and SHA-256
of the exact UTF-8 instruction bytes. Section and invariant prompts have
distinct identities. A semantic prompt edit increments the version; the byte
hash detects an unincremented edit.

Before cache lookup, Backstitch constructs this offline inference contract:

```json
{
  "analysis_contract_version": 1,
  "packet_hash": "<sha256>",
  "prompt": {"id": "...", "version": 3, "sha256": "<sha256>"},
  "provider": {
    "backend_id": "llm",
    "plugin_id": "repository-declared-plugin",
    "model_id": "pkg:service/example.com/repository-declared-model",
    "model_revision": "repository-declared-revision",
    "adapter_id": "backstitch.llm",
    "adapter_version": 2,
    "llm_distribution_version": "installed-version",
    "plugin_distribution_name": "repository-declared-distribution",
    "plugin_distribution_version": "installed-version"
  },
  "request": {
    "json_mode": "require",
    "max_tokens": 16384,
    "reasoning_effort": "max"
  },
  "search_epoch": "1"
}
```

Every field is known from validated configuration, code constants, and packet
bytes without constructing a provider adapter, loading credentials, or making
network traffic. `analysis_key` is SHA-256 of canonical JSON for this contract.
The provider identity additionally carries `llm_distribution_version`,
`plugin_distribution_name`, and `plugin_distribution_version`. The first and
third are resolved before cache lookup with `importlib.metadata.version`; the
plugin distribution name is repository-declared. A missing declared
distribution is exit `2` before traffic in cached modes. Observed model class, provider response model/revision,
response ID, and token usage are opaque provenance only. They never change the
pre-call key and are not compared to declared aliases unless a future keyed
adapter contract defines an exact comparator.

Inference resolution has one immutable owner. A resolved analyzer or verifier
selection contains:

- the stable `ProviderIdentity` above, whose `model_id` is the selected
  canonical Model Monster PURL;
- the analyzer or verifier raw `adapter_model_id` used only as the transport
  selector;
- one frozen `EffectiveRequest`;
- the `RequestIdentity` derived from that exact effective request; and
- the selected trusted capability descriptor and its provenance.

A composed analyzer/verifier selection retains the analyzer and verifier raw
transport selectors separately. A stable PURL is never sent as the raw model
selector merely because both values identify the same model, and a raw
selector never replaces `provider.model_id` in an inference, review, report,
or cache identity. The adapter receives the resolved selection and may only
serialize its frozen effective request plus the already-resolved raw selector
where the transport protocol requires one. It may not add, remove, correct, or
renormalize an inference-affecting request field after `RequestIdentity` is
derived.

`EffectiveRequest` makes a presence decision for every known request field:
`json_mode`, `temperature`, `seed`, `max_tokens`, and `reasoning_effort`. A
present field carries its canonical validated value. An absent optional or
forbidden field is recorded as absent by the immutable resolved value and is
omitted from both the transport body and the closed `RequestIdentity` JSON
projection. Because the field vocabulary is closed, omission is an
unambiguous identity decision, not an adapter default. Adding
`reasoning_effort` to the vocabulary does not add it to an existing logical
request that omits it; such a four-field request keeps byte-for-byte request
projection compatibility. A protocol serialization constant that is not a
user request control is code-owned and must be covered by the keyed adapter
version.

Capability authority is a trusted committed descriptor selected before
inference resolution. Its closed shape is:

```text
{
  capability_schema_version: 1,
  capability_revision,
  provider: {model_id, model_revision},
  request_constraints: {
    json_mode:       {presence, allowed_values, minimum, maximum},
    temperature:     {presence, allowed_values, minimum, maximum},
    seed:            {presence, allowed_values, minimum, maximum},
    max_tokens:      {presence, allowed_values, minimum, maximum},
    reasoning_effort:{presence, allowed_values, minimum, maximum}
  },
  maximum_input_bytes
}
```

`capability_revision`, provider values, and `model_id` are nonblank;
`model_id` is the canonical Model Monster PURL and `maximum_input_bytes` is a
positive integer. The five constraint children are exact; reasoning effort
uses [CFG-6.5]'s closed string domain. Every field rule contains exactly the
four shown members.
`presence` is `required`, `optional`, or `forbidden`; `allowed_values` is null
or a nonempty canonical list in the field's existing value domain; and
`minimum`/`maximum` are both null or form valid inclusive numeric bounds.
Allowed values and bounds cannot coexist. A forbidden rule requires the other
three members to be null. Descriptor provenance is the separately resolved
closed object `{source, source_sha256}`, where `source` is either the committed
repository-relative descriptor source or a nonblank `packaged:` source
identifier and `source_sha256` hashes its exact defining bytes. A descriptor
cannot omit a known field rule, admit an unknown request field, or disagree
with its provenance bytes.

The resolved effective request must satisfy every rule before adapter
construction, credential access, cache work, or provider work. Backstitch
reports the exact dotted configuration key for an incompatible configured
value; it does not silently correct that value. The complete model-request byte
length must not exceed the descriptor's `maximum_input_bytes`.

Mutable provider metadata, local wrapper introspection, and live qualification
observations are not capability authority. A local wrapper may be constructed to
check the committed descriptor only when doing so is provider-free: it may not
read or transmit a credential, perform network traffic, mutate cache state, or
publish an artifact. A descriptor change is reviewed committed input. If it
changes any effective request byte or stable provider identity field, the
ordinary inference-identity rules re-key the request; validation-only
descriptor revision or provenance does not enter `RequestIdentity`,
`analysis_key`, or `review_key`.

Live capability qualification is bounded release-process evidence, not
semantic input or persistent Backstitch artifact authority. It executes the
exact selected descriptor and frozen request under [SEM-9]/[SC-10]. Its
outcome never edits a capability descriptor and never enters packet, prompt,
request, inference, review, cache, result, report, or finding identity.
Elapsed time alone therefore creates neither a cache miss nor a need to
relabel historical results.

`backend_id`, `plugin_id`, `model_id`, and `model_revision` must be nonblank in
`read-write` and `require` modes. They may be blank in `off` mode, where no
cache identity is promised. In off mode a blank `plugin_distribution_name`
maps to `plugin_distribution_version = ""` and performs no plugin distribution
lookup; other allowed blank provider identifiers remain empty JSON strings.
`llm_distribution_version` is always resolved because `llm` is a required
runtime dependency. `require` constructs neither an adapter nor a provider
client.

`json_mode = "prefer"` is a compatibility spelling allowed only with
`cache_mode = "off"`; v1 resolves it unconditionally to `off` before contract
construction. The contract and provider request contain only that resolved
value; `prefer` never appears in either. Structured output is requested only
when configuration names `require` explicitly.
Cached modes require configuration to name `require` or `off` directly. Every
packet causes at most one provider request. Rejection of the resolved request
mode is exit `2`; there is no automatic bare-call fallback under the same event
identity.

The analyzer adapter derives one provider JSON Schema from the current
canonical [EVC-9.1] packet projection when `json_mode = "require"`. The schema
keeps the model response closed. Its `assessment` is a discriminated union of
the classifications whose [SEM-5] required evidence roles exist in the
packet. Evidence is grouped by role; every coordinate is restricted to one
exact `evidence_regions` choice for that role. This is a generation constraint
only. Provider schema enforcement is not trusted; [SEM-5] normalization
independently revalidates the returned role, path, and span against packet
bytes.

The `llm` OpenAI Responses adapter may emit its supported JSON Schema envelope
with `strict = false`. This is a generation aid, not authority. Backstitch does
not patch a private provider builder to change that flag; the closed [SEM-5]
normalizer independently rejects unknown fields, invalid values, and evidence
outside the packet. For a Responses reasoning model the adapter also uses the
wrapper's public reasoning-hiding control so no unused reasoning summary is
requested. That protocol serialization constant is code-owned and covered by
the keyed adapter version, not exposed as a request setting.

The untrusted model response is one closed object with exactly `packet_id`,
`assessment`, `confidence`, `rationale`, and `summary`. `assessment` has
exactly `classification` and `evidence`. `evidence` is a closed object keyed
by the available roles `requirement`, `implementation`, `test`, and
`counterevidence`; each present role contains an array of coordinates with
exactly `path`, `start_line`, and `end_line`. The classification branch
requires each role in [SEM-5]'s minimum set to be present and nonempty.
`confidence` is null or a number from zero through one; `rationale` and
`summary` are strings and `summary` is nonblank. At least one of confidence or
a nonblank rationale is required. Kind, hashes, verification state, code, and
provenance are never accepted from the model.

Changing any inference-contract field creates a new analysis key. Policy,
rendering, concurrency, result/report paths, suppressions, and operational
counters do not.

Backstitch also constructs a provider-independent review contract containing
exactly `analysis_contract_version`, `packet_hash`, `prompt`, `request`, and
`search_epoch` from the inference contract above. `review_key` is SHA-256 of
that contract's canonical JSON. The provider descriptor is deliberately
absent. Equal review keys mean that the complete model-visible packet, semantic
question, normalization/analysis contract, request controls, and explicit
resampling epoch are unchanged. They do not claim that two models would
produce equal output.

The review key supports one product rule: a complete evidence-bound inference
result may remain in force across provider/model selection changes while its
review key is unchanged. The carried unit is the complete canonical result
plus its original inference contract and provenance. Classification,
rationale, summary, selected evidence, `analysis_key`, and producer identity
travel together; no field is relabeled as output from the currently selected
model. Packet, prompt, request, contract, or epoch changes always create a new
review key and cannot carry the old result.

_Implementation mapping_:

- `backstitch/semantic_packets.py`
- `backstitch/semantic_identity.py`
- `backstitch/semantic_verification_contract.py`
- `backstitch/analysis_llm.py`

### 4. Immutable Semantic Cache [SEM-4]

The cache is untrusted and stores versioned canonical objects:

```text
packets/<packet_hash>.json
results/<analysis_key>.json
baselines/<review_key>.json
verify-results/<verify_key>.json
review-locks/<review_key>.lock
review-guards/<review_key>.guard
audit/review-locks/<review_key>.<audit_sha256>.json
locks/<analysis_key>.lock
guards/<analysis_key>.guard
audit/locks/<analysis_key>.<audit_sha256>.json
verify-locks/<verify_key>.lock
verify-guards/<verify_key>.guard
audit/verify-locks/<verify_key>.<audit_sha256>.json
```

The semantic cache is disposable acceleration state. Repository defaults place
it below `.backstitch/`, the repository ignores that directory, and no cache
object is reviewed or committed as ordinary source. Removing an idle cache
root is supported: the next `read-write` run rebuilds needed objects, while a
`require` run reports misses. Fine-grained pruning and concurrent whole-root
deletion are not current Backstitch commands.

CI may restore and save only immutable `packets/`, `results/`, `baselines/`,
and `verify-results/` object trees through a trusted cache service. Lock,
guard, audit, staging, and report trees are never transferred as reusable
cache state. Restore either targets an empty cache root or merges each object
with immutable no-replace validation: an existing byte-identical object is
accepted and different bytes at the same path fail restore. Result trees are
restored before baseline trees. Ordinary archive extraction may not overwrite
or merge divergent baseline trees, and any restored baseline whose target is
absent is corrupt. Restore order therefore cannot choose or replace a baseline.
Restored bytes are untrusted and receive the same complete validation as local
bytes. Cache restoration failure changes only expected call count, cost,
selected disposable baseline, or `require`-mode availability; it cannot change
source, disposition, verification, or policy authority.

A packet object contains exactly `schema_version = 1`,
`object_type = "semantic-packet"`, one current [EVC-9.1] model projection,
and `packet_hash`. The nested projection is contract 3 for section/invariant
or contract 4 for suppression. It never contains instructions. A prompt-only
change therefore reuses the packet object and creates a different result key
without colliding at the packet path.

A result object contains exactly `schema_version = 1`,
`object_type = "semantic-result"`, `inference_contract`, `analysis_key`,
`result`, `provenance`, and `raw_response_sha256`. Its nested canonical
analyzer row is result schema 2 for section and invariant and result schema 3
for suppression. The kind, packet
projection contract, prompt response contract, and nested result schema must
agree exactly; mismatch is corruption, not a cache miss.

A canonical result row contains exactly `schema_version`, `packet_id`,
`kind`, `packet_hash`, `analysis_key`, `classification`, `confidence`,
`rationale`, `summary`, `evidence`, and `verification_state`. Schema 2
retains the exact section/invariant kinds and classifications. Schema 3
requires `kind = "suppression"` and the [SEM-6] suppression classification
vocabulary. Confidence is always present and may be null. Every inference
row remains `evidence_bound`; trusted verification and dispositions project
separately. Evidence uses the exact [SEM-5] packet-local contract for its
kind.

A baseline object contains exactly `schema_version = 1`,
`object_type = "semantic-result-baseline"`, `review_contract`, `review_key`,
and `analysis_key`. Its `analysis_key` names one immutable result object whose
inference contract derives the same review contract. Publication order is
result first, baseline second. Baselines use atomic no-replace publication:
the first valid result selected for a review key remains the baseline until a
review-key input changes. A concurrent loser validates and uses the winner; it
never overwrites it. A baseline with a missing, corrupt, mismatched, or
non-evidence-bound target is corrupt cache, not a miss and not permission to
choose another result.

With `analyze.result_reuse = "evidence-stable"`, lookup checks the baseline
before constructing an analyzer adapter. A valid baseline is a hit even when
its producer differs from the currently selected provider. If no baseline
exists, `read-write` acquires the per-review-key single-flight lock, rechecks
the baseline, validates qualification for any winner, and only then may use or
create the selected provider's exact result and publish the baseline. For a
multi-packet run, it collects all absent-baseline review keys, acquires their
locks in lexical key order, rechecks all baselines, and performs qualification
and the complete call/cost/runtime preflight before any provider work. The
review-lock owner alone elects the first baseline, so concurrent
different-model read-write invocations have at most one active provider call
for each review key and every successful waiter uses the
scheduling-dependent winner. A failed or explicitly cleaned owner may be
retried later under the ordinary single-flight rules; no failed call becomes a
baseline. `require`
takes a lock-free linearizable read: it reads the baseline, validates the
selected provider's exact result or miss when the baseline is absent, then
reads the baseline again. A valid second-read baseline wins and undergoes
qualification validation for its producer. If the second read is absent, the
operation linearizes at that read and may return the valid exact result or its
ordinary exact miss. It performs no lock or baseline write and does not
participate in an in-flight election. With
`"exact-inference"`, baseline objects are ignored and only the selected
provider's exact `analysis_key` may hit. Exact-inference runs do not replace or
repoint an existing baseline. Changing `search_epoch` creates a new review key
and is the supported way to establish a new evidence-stable decision after
explicit resampling.

A newer model selection, provider qualification observation, or passage of
time does not by itself invalidate an evidence-stable baseline. Packet,
prompt, request, analysis-contract, search-epoch, or normalization changes
continue to re-key under [SEM-3]; explicit resampling continues to use
`search_epoch`.

Legacy cache roots remain readable for exact `analysis_key` hits. They have no
baseline objects and therefore grant no cross-provider carry-forward by
themselves. A `read-write` exact hit under the new implementation may
backfill its baseline without changing the result object. No unbounded scan of
legacy `results/` is permitted. Rollout that needs immediate cross-model reuse
warms the cache once with the old selected model before changing selectors.

Verifier event/cache identity, closed result object, reason-free projection,
event key, claim hash, trial-specific effective epoch, normalization, and
provenance are exactly [EVC-3.1]. Analyzer and verifier objects use disjoint
paths and keyed preimages even when they resolve to the same model. Every
verifier hit revalidates its packet, analyzer result, claim, prompt, provider,
request, epoch, evidence, and canonical bytes before it can contribute to an
aggregate. Corruption, mismatch, or require-mode miss is exit `2`, never an
indeterminate model verdict.

Review-key single-flight and verifier single-flight use the same state machine
and filesystem guarantees as analyzer single-flight, substituting
`review_key`, `semantic-review-lock`, `semantic-review-lock-guard`, and the
three review paths shown above, or `verify_key`,
`semantic-verification-lock`, `semantic-verification-lock-guard`, and the
three verifier paths shown above for their analyzer counterparts. Analyzer and
review/verifier keys never share a lock, guard, or cleanup-audit path. The
explicit cleanup command accepts exactly one of `--analysis-key HASH`,
`--review-key HASH`, or `--verify-key HASH`; review and verify cleanup use
their respective paths and key member in the otherwise corresponding closed
audit object. `analyze.lock_wait_timeout_seconds` governs analysis and review
waits; `verify.lock_wait_timeout_seconds` governs verifier waits. Stale age
remains an explicit cleanup-command input rather than repository config.

Analyzer, evidence-stable review, and verifier single-flight use one
parameterized internal ownership coordinator. It owns guard acquisition, lock
creation and validation, ownership tokens, waiting, completion, reincarnation
handling, cleanup, and timeout. Family adapters supply only key/object types,
paths, completion loading/publication, and their closed object validation. The
shared implementation does not change family object bytes, paths, lexical lock
order, audit records, cleanup behavior, or failure priority.

For the review-key substitution, the completion object polled by waiters is
`baselines/<review_key>.json`, not a result path. The owner still publishes and
validates any new analysis result under the nested analysis-key protocol
first. It then publishes the baseline and removes its unchanged token-owned
review lock in one review-guard critical section. Owner failure or timeout
removes every unchanged token-owned review lock already acquired by that run;
process death leaves each one abandoned for explicit cleanup. A result left by
a crash before baseline publication is a valid exact object and may be used to
finish a later election.

Evidence-stable read-write lock order is exactly review key, then analysis key.
When a run needs several review locks it acquires the complete unique set in
lexical review-key order before any analysis lock or provider call. It holds
each outer lock while rechecking the baseline, performing the all-result
qualification and operational preflight, consulting or producing the selected
exact result, publishing the result first, and publishing the baseline second.
No code path acquires a review lock while owning an analysis lock.
Exact-inference uses only the analysis lock. Guard advisory locks remain short
critical sections and never span provider work or waiter sleep. Each lock wait
is bounded by the analyze lock timeout and the whole sequence remains bounded
by the command runtime ceiling.

Provenance has exactly `adapter_id`, `adapter_version`, nullable
`plugin_version`, nullable `model_class`, nullable `provider_model_id`, nullable
`provider_model_revision`, nullable `response_id`, nullable `input_tokens`, and
nullable `output_tokens`. Non-null strings are nonblank and token counts are
nonnegative integers. Arbitrary response headers and raw response text are not
stored. Unknown keys in any recognized cache-object or nested row version are
corruption. An optional index may accelerate lookup but is rebuildable and
non-authoritative.

Cache modes are:

- `off`: do not read or write cache objects; analyzer work calls once per
  packet, while verifier work calls once per normalized finding and configured
  `(base_search_epoch, effective_search_epoch)` pair
- `read-write`: apply the selected analyzer result-reuse rule, reuse each valid
  analyzer or verifier work-item hit, call only for misses, and publish
  successful misses and eligible baselines immutably
- `require`: apply the selected analyzer result-reuse rule, require one valid
  analyzer result for every packet and one valid verifier object for every
  normalized finding/required epoch pair; construct no adapter and make zero
  provider calls; any miss exits `2`

`read-write` is the normal update mode. An inference-relevant change creates
a miss under `exact-inference` for every work identity whose model-visible
packet, prompt, provider, request, contract, or epoch changed. Under
`evidence-stable`, a provider-only change carries the baseline; packet,
prompt, request, contract, and epoch changes miss. Adding support for a new
packet kind does not alter old-kind identities. Changes to suppression scope,
mappings, or matched issues may legitimately alter existing packet projections
and therefore their keys. Meta/rung changes may alter packet eligibility. A
policy-only change remains a zero-call replay. `off` is an uncached run, not a
cache-refresh alias: it neither reads nor publishes cache objects. Changing
`search_epoch` is the explicit resampling mechanism when new immutable cache
objects should be retained.

Every hit recomputes and validates object paths, schemas, hashes, inference
identity, packet identity, prompt/request/provider provenance, result schema,
and evidence against the cached packet projection. Corruption or stale
provenance exits `2`; it never becomes a provider miss.

Mutation of one analysis lock path is serialized by a persistent per-key guard
at `guards/<analysis_key>.guard`. The guard file is the exact canonical object
`{"schema_version":1,"object_type":"semantic-lock-guard","analysis_key":"<hash>"}`,
published with the same immutable no-replace algorithm. Protocol participants
open that regular file and hold an operating-system exclusive advisory lock
for each short critical section that observes, creates, or removes the
corresponding analysis lock. POSIX uses `fcntl.flock`; Windows uses the
stdlib byte-range locking API. The operating system releases the advisory lock
if a process dies; the canonical guard file remains and is reused. Provider
calls and waiter sleeps never occur while holding the guard. Analyzer guard
waits are bounded by `lock_wait_timeout_seconds`; explicit cleanup fails with
exit `2` when the guard is busy rather than waiting without a configured bound.

Miss acquisition is the `semantic-cache-single-flight` state machine:

1. validate that no result exists;
2. construct a complete record containing exactly `schema_version = 1`,
   `object_type = "semantic-lock"`, `analysis_key`, a random lowercase
   64-hex `owner_token`, positive integer `pid`, nonblank `host`, and
   `created_at_utc` in canonical UTC RFC 3339 form;
3. while holding the per-key guard, recheck the result, write and fsync that
   record to a same-directory mode-`0o600` temporary,
   publish it atomically with no replacement using `os.link`, unlink the
   temporary, and fsync the directory where supported; link success is lock
   ownership and `FileExistsError` is waiter state, so no partial lock record
   can become authoritative;
4. after acquisition, recheck the result path; a valid result is a hit, causes
   token-checked lock removal, and causes no call;
5. only the unchanged token's owner that still observes a miss may call the
   provider or remove the lock;
6. a waiter polls at an implementation-owned interval no greater than one
   second for a valid result until `lock_wait_timeout_seconds`, never calls the
   provider, and never removes or steals the lock; it validates any complete
   lock it observes but does not pin an owner token, because owner A may fail
   and owner B may acquire the absent path while the waiter remains passive;
7. a caught owner failure removes only its unchanged token-owned lock; process
   death leaves an abandoned lock.

Before publishing a provider result and again before owner cleanup, the owner
holds the per-key guard, reopens, and validates the complete lock bytes and
token. Result publication and owned-lock removal occur in that same critical
section. A mismatch exits `2` without publishing or deleting. Protocol
participants never replace a lock path: they only create absent paths, wait,
or remove a validated owned/stale path while holding the guard. The guard is
what closes the otherwise valid read-then-unlink reincarnation race between
cleanup and a new analyzer. Hostile non-participant filesystem mutation is
outside the local cache threat model; untrusted bytes at every observation
remain in scope.

Publication uses local-filesystem no-replace semantics without a new
dependency: write and fsync a same-directory temporary file, hard-link it to
the final path with `os.link`, unlink the temporary file, and fsync the
directory where supported. `FileExistsError` requires byte-for-byte validation
of the existing object; different bytes are corruption. Cache roots that do
not support same-filesystem hard links and atomic directory entry operations
are unsupported and exit `2`. The same-filesystem hard-link publication path
must be exercised in hermetic tests. Runtime platform support is defined by
[EVC-8.2]; a dependency-only Windows CI lane does not establish runtime
support. Directory fsync is required only where the platform supports opening
and syncing directories.

An abandoned lock is removed only by:

```bash
backstitch cache cleanup-lock --cache-path PATH \
  --analysis-key HASH --lock-stale-seconds SECONDS --reason TEXT
backstitch cache cleanup-lock --cache-path PATH \
  --review-key HASH --lock-stale-seconds SECONDS --reason TEXT
backstitch cache cleanup-lock --cache-path PATH \
  --verify-key HASH --lock-stale-seconds SECONDS --reason TEXT
```

The command does no config discovery. It requires a nonblank reason and a
positive explicit stale interval. It acquires the per-key guard without an
unbounded wait and holds it from the first lock snapshot through audit
publication and removal. A second cleanup or analyzer therefore cannot remove
the old path and install a fresh lock between validation and unlink. For a
valid lock, age starts at
`created_at_utc`; for a malformed legacy lock, age starts at filesystem
`mtime_ns`. Before deletion it builds a closed audit object with exactly
`schema_version = 1`, `object_type = "semantic-lock-cleanup"`, `analysis_key`,
`lock_sha256`, base64 `lock_bytes`, `lock_lstat` (`mode`, `size`, `mtime_ns`),
`reason`, and `cleaned_at_utc`. Its path is
`audit/locks/<analysis_key>.<audit_sha256>.json`, where `audit_sha256` hashes
the complete canonical audit object. It publishes that object with no
replacement, then removes the lock only if its bytes and lstat identity are
unchanged. A retry after audit publication creates or validates its own audit
event and may remove the still-unchanged stale lock. It never runs or retries
analysis.

The review-key variant performs the same algorithm with closed
`semantic-review-lock-cleanup` audit objects containing `review_key` instead
of `analysis_key` and publishes them at
`audit/review-locks/<review_key>.<audit_sha256>.json`. Its lock and guard
objects likewise contain `review_key` and use the review object types and paths
shown above. Cleanup never nests lock acquisition: analysis-, review-, and
verify-key cleanup owns only the matching guard.

Canonical result JSONL rendered from fixed packet order and cache objects is
byte-identical on replay. Run-local duration, wait time, cache counters, and
process identity live only in operational reports.

_Implementation mapping_:

- `backstitch/semantic_cache.py`
- `tests/test_semantic_cache.py`
- `tests/test_semantic_cache_coordinator.py`
- `tests/test_semantic_verification.py`

### 5. Evidence And Verification State [SEM-5]

Model evidence is a closed object keyed by roles available in the packet.
Each coordinate under a role contains `path`, `start_line`, and `end_line`;
spans are inclusive. An unavailable role key or any extra coordinate field,
including role, excerpt, hash, packet identity, or provenance, is malformed.
Trusted normalization reconstructs canonical entries containing role and
requires each role/path/span to match exactly one region in the same maximal,
deduplicated model-visible projection that produced `evidence_regions`, and
reconstructs canonical evidence with the exact `excerpt` and
`excerpt_sha256` from that projected source. Hidden contained or equal source
records cannot make one model-visible choice ambiguous. Zero or multiple
matching projected regions is malformed.
Duplicate evidence is malformed. Canonical evidence sorts by role, path,
start line, end line, and excerpt hash.

Current packet-schema-3 role sources are exact and common across obligation
kinds:

| Role | Packet source |
|------|---------------|
| `requirement` | nonblank `requirement.text` |
| `implementation` | nonblank `declared_evidence[].snippet` whose model role is `implementation` |
| `test` | nonblank `declared_evidence[].snippet` whose model role is `test` |
| `counterevidence` | nonblank `counterevidence[].snippet` |

Every model evidence row must equal one packet `evidence_regions` row.
`counterevidence` is advisory evidence only: it may support or challenge an
analyzer/verifier rationale, but it never satisfies a required
`implementation` or `test` role. Historical packet-schema-2 owner/target/
binding-test sources are migration vocabulary only and never enter current
analysis or cache identity. Current invariant result rows do not carry the old
packet `content_hash`.

The minimum required role set is:

| Kind and classification | Required roles |
|-------------------------|----------------|
| section `ok` | none |
| section `confirmed_mismatch`, `probable_mismatch` | `requirement`, `implementation` |
| section `missing_trace`, `ambiguous` | `requirement` |
| invariant `ok` | `test` |
| invariant `weak_binding` | `requirement`, `implementation` |
| invariant `confirmed_mismatch`, `probable_mismatch` | `requirement`, `implementation` |
| invariant `ambiguous` | `requirement` |

Missing, invalid, or out-of-range required evidence makes model output
malformed. Invariant `ok` without `test` evidence normalizes to
`weak_binding` only when its `requirement` and `implementation` roles are
satisfied; otherwise it is malformed. `missing_trace` is section-only, remains
an evidence-bound absence finding, and can never become mechanically
verified merely from bounded packet evidence.

Suppression result rows use result schema 3 and the same closed packet-local
evidence representation. Section and invariant result rows remain schema 2.
Suppression `ok` and `rationale_insufficient` require `requirement`;
`scope_overbroad` and `risk_unaddressed` require `requirement` and
`counterevidence`; `ambiguous` requires `requirement`. Missing or
out-of-range evidence is malformed. Model normalization produces only
`evidence_bound`; the existing verification and human-disposition authority
rules do not change.

Evidence ranges are deterministic. A nonblank requirement covers its stored
inclusive `start_line` through `end_line`, and its `text` has exactly that many
logical lines. A nonblank declared or counterevidence region covers its stored
inclusive span, and its `snippet` has exactly that many logical lines.
Canonical excerpt bytes are the corresponding stored packet text joined with
`\n`, without reading the repository again.
`excerpt_sha256` is lowercase SHA-256 of the UTF-8 encoding of those exact
canonical excerpt bytes.

Verification state is trusted metadata and is never accepted from the model:
`evidence_bound`, `verification_indeterminate`, `independently_verified`,
`mechanically_verified`, `human_verified`, `disputed_by_verifier`, or
`human_rejected`. Model normalization produces only `evidence_bound`.
Composition follows [EVC-6]'s exact first-match precedence: human disposition,
named mechanical predicate, aggregate blinded verification, then analyzer.
Legacy `corroborated` is read-only input normalized to `evidence_bound`; new
producers never emit it or generic `disputed`.

Only `mechanically_verified` and `human_verified` are failure-authoritative by
default. `independently_verified` gains authority only for an exact qualified
code/context selector under [EVC-6]/[EVC-10.1]. Evidence-bound,
verification-indeterminate, and both disputed contexts never cause exit `1`.
Configuration that grants authority outside those rules is invalid and exits
`2` before cache/provider work.

`SEMANTIC_MISSING_TRACE` is not emitted for a syntactically absent mapping,
backlink, bind, or binding-test relation. Those are deterministic readiness
debt and block current analysis before provider work. `missing_trace` is
available only when reciprocal graph syntax is complete but bounded packet
content is judged not to establish the claimed behavioral relation.

_Implementation mapping_:

- `backstitch/semantic_evidence.py`

### 6. Semantic Diagnostics, Findings, And Dispositions [SEM-6]

Every non-`ok` canonical result projects by classification to exactly one
stable diagnostic. The long code is canonical in artifacts, finding identity,
policy, and dispositions; the short code is a display and selector alias:

| Classification | Canonical code | Short code |
|---|---|---|
| `confirmed_mismatch` | `SEMANTIC_CONFIRMED_MISMATCH` | `BSA001` |
| `probable_mismatch` | `SEMANTIC_PROBABLE_MISMATCH` | `BSA002` |
| `missing_trace` | `SEMANTIC_MISSING_TRACE` | `BSA003` |
| `weak_binding` | `SEMANTIC_WEAK_BINDING` | `BSA004` |
| `ambiguous` | `SEMANTIC_AMBIGUOUS` | `BSA005` |

| Suppression classification | Canonical code | Short code |
|---|---|---|
| `rationale_insufficient` | `SEMANTIC_SUPPRESSION_RATIONALE_INSUFFICIENT` | `BSA006` |
| `scope_overbroad` | `SEMANTIC_SUPPRESSION_SCOPE_OVERBROAD` | `BSA007` |
| `risk_unaddressed` | `SEMANTIC_SUPPRESSION_RISK_UNADDRESSED` | `BSA008` |

Suppression classifications are `ok`, `rationale_insufficient`,
`scope_overbroad`, `risk_unaddressed`, and `ambiguous`; `ambiguous` retains
`SEMANTIC_AMBIGUOUS`/`BSA005`. The three new codes use the existing
`confirmed_mismatch` packaged level row across verification states. Their
finding hashes use `packet_kind = "suppression"` and otherwise retain the
exact finding contract. Evidence-bound findings never decide whether the
deterministic suppression applies. Ordinary `finding_handling` and exact
dispositions govern their debt and human disposition.

Tool, provider, cache, input, and malformed result failures never project to
BSA diagnostics. Section classifications are `ok`, `confirmed_mismatch`,
`probable_mismatch`, `missing_trace`, and `ambiguous`. Invariant
classifications are `ok`, `weak_binding`, `confirmed_mismatch`,
`probable_mismatch`, and `ambiguous`.

The exact packaged levels are:

| Code | evidence_bound | verification_indeterminate | independently_verified | mechanically_verified | human_verified | disputed_by_verifier | human_rejected |
|---|---|---|---|---|---|---|---|
| `SEMANTIC_CONFIRMED_MISMATCH` | warning | warning | warning | warning | warning | info | info |
| `SEMANTIC_PROBABLE_MISMATCH` | info | info | warning | warning | warning | info | info |
| `SEMANTIC_MISSING_TRACE` | warning | warning | warning | warning | warning | info | info |
| `SEMANTIC_WEAK_BINDING` | warning | warning | warning | warning | warning | info | info |
| `SEMANTIC_AMBIGUOUS` | info | info | info | info | info | info | info |
| `SEMANTIC_SUPPRESSION_RATIONALE_INSUFFICIENT` | warning | warning | warning | warning | warning | info | info |
| `SEMANTIC_SUPPRESSION_SCOPE_OVERBROAD` | warning | warning | warning | warning | warning | info | info |
| `SEMANTIC_SUPPRESSION_RISK_UNADDRESSED` | warning | warning | warning | warning | warning | info | info |

For each diagnostic, `finding_hash` is SHA-256 of canonical JSON containing:

```json
{
  "finding_contract_version": 1,
  "code": "SEMANTIC_...",
  "classification": "...",
  "packet_kind": "section|invariant|suppression",
  "packet_id": "...",
  "packet_hash": "<sha256>",
  "evidence": [
    {
      "role": "...",
      "path": "...",
      "start_line": 1,
      "end_line": 1,
      "excerpt_sha256": "<sha256>"
    }
  ]
}
```

Evidence uses the canonical order from [SEM-5]. Summary, rationale,
confidence, verification state, analysis key, model/provider provenance,
severity, policy, and rendering are excluded. Presentation text never becomes
identity under another name.

A disposition is a closed `[[analyze.dispositions]]` record with exactly
`code`, `packet_id`, `packet_hash`, `finding_hash`, `status`, and `reason`.
`code` must be one canonical long code from this section. It matches canonical
code, packet ID, packet hash, and finding hash exactly. `accepted` produces
`human_verified`; `rejected` produces `human_rejected`.
Duplicate disposition identities are configuration errors even when their
remaining bytes match. Blank reasons and unknown statuses are configuration
errors. Unmatched dispositions are reported as unused and remain auditable.

Selectors retain `CODE:context`, short-code aliases, globs, and later-rule-wins
precedence for visibility. Failure authority is narrower: any semantic level
that contributes to exit `1` through `fail_on` must come from an exact,
non-glob canonical or short code paired with the exact context
`human_verified` or `mechanically_verified`. Wildcards may lower or neutralize
severity but may never grant semantic failure authority. Configuration
validation computes the final level and winning rule for every semantic code by
verification state and rejects any semantic code/state whose winning rule is
not exact while its level is in `fail_on`. The exact
`CODE:independently_verified` exception requires the passing, identity-matched
[EVC-10.1] enforce artifact and strong-selector checks in [EVC-6].

For semantic policy materialization, rule position is zero-based within the
source layer that declared the rule. When more than one selector in the winning
rule matches, `winning_policy_rule.selector` is the first matching selector in
that rule's configured order. `winning_policy_rule.source` is the exact ordered
layer identifier: `packaged:backstitch/defaults.toml` for packaged policy and
the resolved source path for each extended or selected repository file.
`effective_policy_layers` lists every such layer in merge order, including
extended parents. A final semantic level of `off` remains in
`analysis-report.semantic_diagnostics` with `severity = "off"` and its winning
rule as the semantic audit surface, but it is omitted from stderr and has no
exit effect.

`finding_handling` is exact:

- `allow`: show and count undisposed findings; create no debt warning and no
  exit effect
- `report`: additionally record each undisposed finding in
  `finding_debt` and emit a concise stderr warning; no exit effect
- `require_disposition`: record the same debt and exit `2` when any finding
  remains undisposed

`candidate_handling` is a one-release deprecated config alias for
`finding_handling`; it never appears in producer output. Supplying both names,
whether equal or conflicting, is invalid configuration. The noun `candidate`
is reserved for discovered source under [EVC-7].

Cached classification stays policy-neutral. Changing policy or dispositions
reprojects the same cache objects with zero provider calls.

_Implementation mapping_:

- `backstitch/semantic_policy.py`

### 7. Completeness, Reports, Budgets, And Exit Codes [SEM-7]

Packet generation accepts an optional sidecar:

```bash
backstitch packets ... --output packets.jsonl --report packet-report.json
```

The resolved packet output and non-null report paths must be distinct. Equality
is invalid input and exits `2` before temporary creation or publication.

Current generation emits the packet-report schema 3 in [EVC-9.1], including
source snapshot, derivation contract, readiness counts, alignment audit,
effective deterministic issues, exact packet/report byte counts and digests,
and content identity. The following schema-1 object is historical validation
vocabulary only and cannot satisfy current completeness:

```json
{
  "schema_version": 1,
  "artifact": "backstitch-packet-report",
  "packet_jsonl_sha256": "<sha256>",
  "kind": "section|invariant|all",
  "eligible_counts": {"section": 0, "invariant": 0},
  "emitted_counts": {"section": 0, "invariant": 0},
  "packet_warning_count": 0,
  "prompt_byte_count": 0,
  "packets": [{"packet_id": "...", "packet_hash": "<sha256>"}]
}
```

Eligible counts are computed after the complete deterministic report and
before `--kind` filtering: edge-bearing sections and bound invariants with an
emittable packet. Emitted counts are after kind filtering and all caps.
`packet_warning_count` counts warning strings, not packets containing warnings.
`prompt_byte_count` sums, over emitted packets, exact UTF-8 bytes of the
code-owned prompt instructions, two newline bytes, and canonical projection.
Packet entries preserve JSONL order. The digest covers the exact final JSONL
bytes including newlines.

These schema-1 eligible/emitted counts and prompt totals apply only to
historical packet-schema-2 validation. They do not appear in current reports.
A current schema-3 report is emitted only for complete `--kind all` packet
output and follows [EVC-9.1]'s exact full-corpus recomputation rules.

Historical analysis accepts:

```bash
backstitch analyze --packets packets.jsonl \
  --packet-report packet-report.json \
  --output analysis.jsonl --report analysis-report.json
```

Current analysis instead accepts `backstitch analyze --repo-root PATH` and
derives packet/report bytes inside [EVC-5.1]'s capture/recapture boundary.

Current repository analysis has one preparation/execution lifecycle.
`prepare_analysis` resolves configuration and inference, captures the accepted
source snapshot, derives readiness, and produces the authoritative complete
packet plan with the exact canonical packet and model-request bytes retained
for execution. It is provider-free and has no semantic side effects: no
provider call, credential read, cache read or mutation, output temporary,
result/report publication, or partial packet/report publication is permitted.
`analyze --preflight` renders this same preparation and stops. Ordinary
`analyze` calls `prepare_analysis` once and passes the returned immutable value
to `execute_prepared_analysis`; it does not rebuild readiness, packets,
prompts, request identity, or budget facts through another path.

Execution performs two currentness recaptures against the preparation's source
snapshot and derivation identity. The first occurs before any semantic cache
lookup, cache mutation, adapter/provider work, or semantic output temporary.
A mismatch exits `2` with zero such work. The second occurs after all selected
results are available and immediately before current result/report
publication. A mismatch there exits `2` and publishes no current result or
report; immutable cache objects already completed by the attempted analysis
remain disposable historical acceleration state and gain no current-source
authority. The final publication uses only the canonical packet,
model-request, result, and report bytes derived from or joined to the accepted
preparation. Neither recapture reparses a prepared packet or changes an
identity.

Preparation is also the sole budget authority for the current corpus.
`analyze.maximum_prompt_bytes` retains its existing aggregate meaning:
`prompt_byte_count` is the sum of exact `model_request_bytes` over every
selected packet, regardless of cache-hit expectation. It is never a
per-request or per-packet ceiling. Independently, each complete selected
`model_request_bytes` value must fit the trusted capability descriptor's
`maximum_input_bytes`. The same retained bytes are counted, keyed, and sent.
A failure of the aggregate prompt ceiling or any per-request capability
ceiling exits `2` before cache or provider work; no second materialization may
produce different bytes after the check.

The resolved analysis output and non-null report paths must be distinct.
Equality is invalid input and exits `2` before temporary creation, cache work,
adapter construction, provider work, or publication.

`--packet-report` is required for every historical `--packets` replay. Its
schema, content digest, packet IDs/hashes, source claim, alignment audit,
readiness counts, byte counts, and derivation identities must satisfy
[EVC-9.1] before cache or provider work. Packet-schema-2 input remains bounded
historical validation/presentation only and cannot produce this report.

The current analysis report is the closed schema 6 contract in [EVC-9.1];
historical analysis retains the closed schema 3, 4, and 5 readers. The current contract
retains the following analyzer fields from schema 3 and the former schema-1
report while adding scope, semantic status, artifact integrity/currentness,
source provenance/snapshot, packet-report content hash, alignment summary and
audit, deterministic issues, and the closed verification object. Retained
fields include
`artifact = "backstitch-analysis-report"`, `packet_jsonl_sha256`,
`result_jsonl_sha256`, `status` (`complete`, `incomplete`, or `failed`),
`analysis_exit_code`, `packet_count`, `result_count`, `packet_warning_count`,
`packet_warning_debt`, `finding_debt`, `cache_hits`, `cache_misses`,
`provider_calls`, `result_reuse`, `exact_cache_hits`, `carried_results`,
`selected_inference`, `result_sources`, `result_providers`,
`prompt_byte_count`, `elapsed_milliseconds`, nullable
`estimated_cost_microusd`, nullable `cost_rate_source`,
`effective_policy_layers`, `semantic_diagnostics`, `unused_dispositions`, and
`problems`. `analysis_exit_code` is the pre-publication semantic/completeness
decision; an output publication failure can still make the command and returned
run exit `2`. Canonical result JSONL is policy-neutral and byte-stable; this
operational report is not.

Current packet and analysis reports include closed suppression eligible,
emitted, result, cache-hit, provider-call, classification, diagnostic, and
debt counts. `require_complete` covers every emitted suppression packet. A
valid current packet-report schema 3 is intrinsically complete: `eligible` and
`emitted` both count the selected executable/evaluate population, and every
selected audit row has exactly one packet. A forged difference is an invalid
packet report and exits `2` before adapter construction. A required
`suppression` kind therefore records policy intent; zero eligible
suppressions is vacuously complete so deleting the last suppression does not
break CI.

Packet-report schema 3 and analysis-report schema 6 are the current producer
contracts. Readers retain exact packet-report schema 2 and analysis-report
schema 3, 4, and 5 support. Compatibility readers never invent result-reuse
metadata or reinterpret an old row as a suppression row.
Analysis-report schema 4 added `packet_schema_versions` from packet-report
schema 3 and `kind_counts`; schema 5 retains both. `kind_counts` contains exactly `eligible`,
`emitted`, `results`, `cache_hits`, `cache_misses`, and `provider_calls`;
each contains exactly nonnegative `section`, `invariant`, and `suppression`
integers. Eligible/emitted copy the packet report. Results and work counts
recompute from canonical rows and operational events; each nested total
equals the corresponding existing aggregate count.

Schema 5 added `result_reuse`, `selected_inference`, `exact_cache_hits`,
`carried_results`, `result_sources`, and `result_providers`. `result_reuse` is
the resolved [SEM-4] enum. Schema 6 retains those fields and adds
`selected_inference.adapter_model_id`. Its `selected_inference` contains
exactly `provider`, `adapter_model_id`, `request`,
`analysis_contract_version`, `search_epoch`, and `prompts`. The raw adapter
model ID is the nonblank analyzer transport selector selected for this run; it
is operational provenance and is excluded when reconstructing
`analysis_key` or `review_key`. The provider, request, and contract members
have their exact [SEM-3] inference-contract shapes.
`prompts` is in canonical packet-kind order and each row contains exactly
`kind` plus that kind's code-owned `id`, `version`, and `sha256` prompt
descriptor. It supplies the selected-provider preimage needed to reconstruct
the selected analysis key for each packet without consulting configuration:
the packet kind selects a row, and only that row's `id`, `version`, and
`sha256` form the inference-contract prompt. `kind` is report indexing, not a
review- or inference-contract member.

`result_sources` is in canonical result-row order and has one closed row per
result containing exactly `packet_id`, `packet_hash`, `analysis_key`,
`review_key`, `result_object_sha256`, `inference_contract`, `provenance`, and
`selection`. `selection` is `live`, `exact-cache`, or `carried`. Each row joins
exactly one canonical result by packet identity and hashes. Report production
passes the ordered selected closed result envelopes to the validator as
authoritative inputs; cache-off live work constructs the same envelope in
memory without persisting it. Report production also passes an ordered,
non-report operational selection event per result containing exactly
`packet_id`, `packet_hash`, `result_object_sha256`, and `selection`. This event
is created at the runtime branch that observed a newly produced result, an
existing result whose analysis key equals the selected key, or a baseline
whose result key differs from the selected key. Those cases are respectively
`live`, `exact-cache`, and `carried`; it is not derived from the report. The
validator requires
each persisted source row to equal its event, hashes each complete envelope to
reproduce `result_object_sha256`, requires the row inference contract and
provenance to equal that envelope, hashes `inference_contract` to reproduce
`analysis_key`, removes its provider to reproduce the exact review contract
and `review_key`, and validates its packet, nested result, and prompt against
the joined inputs. It independently reconstructs the selected analysis key
from `selected_inference`: `carried` is required exactly when the row analysis
key differs; `live` or `exact-cache` is required when it equals. A validator
invocation without both the ordered selected envelopes and ordered operational
selection events is invalid; report fields never attest to their own producer
provenance or cache/live source.

`exact_cache_hits` and `carried_results` are nonnegative integers whose sum is
`cache_hits`. They respectively count `exact-cache` and `carried`
`result_sources` rows. `live` rows are successful current provider calls;
provider failures may make `provider_calls` greater than the live-row count,
and the existing operational-fact validation owns that reconciliation.
`result_providers` is sorted by canonical JSON of `provider` plus
`observed_model` and contains one row per distinct producing identity with
exactly `provider`, `observed_model`, `result_count`, and
`carried_result_count`. `provider` has the exact [SEM-3] provider shape.
`observed_model` contains exactly nullable `model_class`,
`provider_model_id`, and `provider_model_revision` copied from the immutable
`result_sources.provenance`. Counts are recomputed from the source ledger,
are nonnegative,
`carried_result_count <= result_count`, provider result counts sum to
`result_count`, and provider carried counts sum to `carried_results`. Live
results and exact hits retain the selected provider and their observed return
identity; carried rows retain their original producer. Every other schema-4
field and semantic rule is unchanged.

Every invocation that reaches artifact publication constructs its result and
report from that invocation's current or historical input, valid exact or
baseline-selected cache hits, live misses, and current policy. A failure before
report publication remains an explicit error and log event. A prior output
file or report is never used as a semantic cache and never satisfies
completeness; only [SEM-4] immutable cache objects may do so. Run artifacts may be
overwritten atomically by later invocations and may be retained as short-lived
CI artifacts; they are not ordinary repository source.

Nested analysis-report records are also closed. A schema-3 problem has exactly
nullable `packet_id`, nullable `obligation_id`, `stage`, `code`, `message`, and
required closed `details`. Existing SEM stage/code pairs use empty details;
[EVC-8.7] owns the additional alignment, snapshot, input, packet-report-budget,
and qualification pairs plus their exact detail shapes. The existing stage is one of `config`, `input`,
`cache`, `lock`, `provider`, `normalization`, `completeness`, `budget`,
`output`, or `internal`. Code is one of `invalid_config`, `invalid_input`,
`corrupt_cache`, `stale_cache`, `lock_timeout`, `provider_failure`,
`malformed_result`, `incomplete_result`, `budget_exceeded`, `output_failure`,
or `internal_failure`, paired with its corresponding stage. Legacy schema-1
packet-warning debt entries have exactly `packet_id` and `warnings`, preserving
packet order and warning-string order; the aggregate list length across entries
equals `packet_warning_count`. That record shape is historical validation and
presentation vocabulary only; every schema-3 report requires zero count and
empty debt. Finding-debt
entries contain exactly canonical `code`, `packet_id`, `packet_hash`,
`finding_hash`, and `verification_state`. Each semantic diagnostic contains
exactly canonical `code`, `short_code`, `classification`, `packet_kind`,
`packet_id`, `packet_hash`, `finding_hash`, `verification_state`, `evidence`,
`default_severity`, `severity`, `summary`, `rationale`, `analysis_key`, and
`winning_policy_rule`. A winning rule has exactly `source`, `position`,
`selector`, and `level`. Effective policy layers are ordered source-path
strings. Unused dispositions preserve the exact closed disposition records.
Semantic diagnostic `severity` is one of `error`, `warning`, `info`, or `off`;
`default_severity` is never `off` under the packaged policy.

Status is `failed` when a pre-publication problem is at stage config, input,
cache, lock, provider, normalization, output, or internal; otherwise it is
`incomplete` when a completeness/budget problem exists or required finding
disposition is absent; otherwise it is `complete`. `analysis_exit_code`
follows [SEM-7] precedence from that state and diagnostics. A later publication
failure appears in the returned run problems
and final exit; if the report itself could not be published, it cannot falsely
claim to contain that event.

A packet model/provider/normalization failure emits no canonical result row and
no BSA diagnostic. It appends one closed structured problem with nullable
`packet_id`, nullable `obligation_id`, `stage`, `code`, `message`, and required
closed `details`, continues with later packets subject to budgets,
makes the report status `failed`, and forces exit `2`. Such a problem never
satisfies `require_complete`. The returned JSONL may therefore contain valid
rows for successful packets only. Historical mode may publish its explicitly
requested failed-run artifacts under its ordinary atomic contract. Current
mode stages all outputs and publishes no current result/report until recapture
matches; an output failure still takes precedence. There is no `ambiguous`
error-row escape hatch.

Schema-3 analysis reports have `packet_warning_count = 0` and
`packet_warning_debt = []` for both current-repository and historical-snapshot
scope. The legacy schema-1 report validator may preserve packet-warning count
and ordered debt for historical validation and presentation only; that
vocabulary cannot satisfy a schema-3 gate and has no current policy authority.

Cost is a conservative pre-call ceiling:

```text
estimated_input_tokens = prompt_utf8_bytes + input_token_overhead
ceil(estimated_input_tokens * input_cost_microusd_per_million_tokens / 1_000_000)
+ ceil(max_tokens * output_cost_microusd_per_million_tokens / 1_000_000)
```

For each supported backend/plugin pair, the keyed adapter contract must declare
that prompt content token count cannot exceed UTF-8 byte length and must expose
a code-owned minimum framing-token bound. `input_token_overhead` must be at
least that bound; an unknown pair cannot use a positive cost ceiling.
The estimate is summed across planned misses
before traffic. A positive
`maximum_estimated_cost_microusd` requires nonnegative integer input/output
rates, nonnegative overhead, and a nonblank `cost_rate_source`; a zero rate is
valid for a documented free direction. When the maximum is zero and
rates/source are absent, the cost gate is disabled and report cost fields are
null, never a fabricated zero.
Provider-reported usage and cost are provenance only. Code contains no provider
price table.

Timeout ownership is explicit. `lock_wait_timeout_seconds` bounds waiting on
another cache owner. Stale age is supplied only by explicit cleanup CLI flag
`--lock-stale-seconds`. `maximum_runtime_seconds` is checked before scheduling work and after
each provider return; it stops new calls and makes an overrun exit `2`, but the
first implementation does not claim it can cancel an arbitrary in-flight
`llm` request. The former `timeout_seconds` key is removed, not silently
reinterpreted. A hard per-call timeout requires a future adapter contract with
real cancellation. No timeout becomes a target finding or an automatic
cache-miss retry.

For a composed analyze/verify operation, one whole-operation monotonic
deadline starts immediately before semantic cache preflight. It uses
`analyze.maximum_runtime_seconds` when verification is disabled and the
minimum of analyze and verify `maximum_runtime_seconds` when verification is
enabled. Both stages receive that same absolute deadline. A stage-specific
lock wait remains capped by its own lock-wait setting but cannot extend the
whole-operation deadline.

Exit precedence is:

| Condition | Exit |
|-----------|-----:|
| Invalid config/input, duplicate IDs, corrupt/stale cache, lock timeout, provider failure, malformed result, output failure, or internal failure | 2 |
| Missing required kind/count/report, or count/prompt/call/runtime/cost budget exceeded | 2 |
| Any packet lacks one valid result when `require_complete = true` | 2 |
| `finding_handling = "require_disposition"` and an undisposed finding remains | 2 |
| Eval enforce mode has an undefined metric, unmet sample floor, or failed threshold | 2 |
| Required analysis completed and an exact human/mechanical diagnostic, or exactly qualified independently-verified diagnostic, has an effective level in `fail_on` | 1 |
| Otherwise | 0 |

Tool and completeness failures take precedence over target findings. Policy
cannot convert them to exit `0` or `1`.

Report trust boundaries validate the closed top-level shape and ordered
field domains before recomputing alignment, count, identity, and content-hash
claims. A report with multiple defects fails at the first invalid contract
phase; later defects cannot mask or reorder that error.

_Implementation mapping_:

- `backstitch/artifact_publication.py`
- `backstitch/packet_application.py`
- `backstitch/semantic_analysis.py`
- `backstitch/semantic_application.py`
- `backstitch/semantic_budget.py`
- `backstitch/semantic_reports.py`
- `backstitch/cli.py`

### 8. Measured Semantic Evaluation [SEM-8]

The promoting public entry point is:

```bash
backstitch eval --corpus tests/semantic_eval/v3/manifest.json \
  --output semantic-eval-report.json
```

Current qualification is the complete composed analyzer/verifier corpus,
schema-3 report, exact metrics, trial-specific verifier epochs, cold-primary
and zero-call replay, authoritative recomputation, and strong policy selector
contract in [EVC-10.1]. It is configured only by
`[tool.backstitch.verify.eval]`. This is the sole promoting path. It measures
stable, adversarial, replayable, within-repository precision and sensitivity;
it does not measure or require cross-model correlation.

The analyzer-only v1 corpus and schema-2 eval report described below remain
bounded historical measurements. Their loader may validate and render them,
but `[tool.backstitch.analyze.eval]` is not a current producer setting and
neither a historical pass nor its former enforce mode grants policy authority.

`eval` accepts `--config` and `--no-config`; discovery anchors at the manifest
parent. It builds every case through production scan, resolution,
packetization, semantic analysis, evidence, cache, and policy. It never accepts
hand-built packets/results. It exits `2` for corpus, transform, provider,
cache, artifact, or output failure. In report mode, undefined metrics are
`null` and do not fail. In enforce mode, undefined or under-sampled metrics and
threshold failures exit `2`. `eval` never exits `1` because qualification is a
tool/corpus decision, not a target-repository finding.

Each isolated eval attempt sets the repository inventory floor
`minimum_packets` to zero, uses `finding_handling = "allow"`, and supplies no
human dispositions. Those controls govern the dogfood repository and cannot
invalidate or relabel an eval fixture. Required kinds, completeness, packet
and prompt ceilings, provider/cost/runtime budgets, request identity, cache,
evidence validation, policy projection, and all eval-specific sample floors
and thresholds remain active.

The resolved corpus manifest and report output paths must be distinct. Equality
is rejected before manifest loading, adapter construction, cache access,
temporary fixture creation, or output publication. This protects the
authoritative corpus from being replaced by its derived report.

Eval rejects `cache_mode = "off"` before adapter construction. Its primary
phase uses the configured `read-write` or `require` mode. Each trial then runs
an internal replay phase with require semantics against the same cache,
constructing no adapter: read-write may populate primary misses, while require
must hit in both phases. Any replay miss or provider call is exit `2`. This
phase rule is part of eval orchestration and does not rewrite the resolved
repository setting reported in the artifact.

The manifest is closed and has exactly `schema_version = 1`, nonblank
`corpus_id`, nonblank `corpus_version`, and unique ordered `cases`. Unknown
keys at any manifest nesting level are invalid. Paths are manifest-relative,
cannot escape, and cannot be symlinks.

Each case contains `case_id`, `family`, `fixture`, `fixture_sha256`, one
`transform`, and `variants.clean`/`variants.mutated`. Fixture hash is SHA-256 of
canonical JSON shaped exactly as
`{"files":[{"path":"<relative-posix>","sha256":"<sha256>"}]}` with file
items sorted by path. A
transform contains `path`, `source_sha256`, `before`, `after`, and
`mutated_sha256`. The runner copies the clean fixture, verifies hashes,
requires `before` exactly once, replaces it, verifies the mutated hash, then
runs the production path. Gold data never enters the copied fixture or request.

Each variant has exactly label (`positive` or `negative`),
`expected_packet_id`, `expected_packet_kind` (`section` or `invariant`), and
`critical`. Positive variants also have `expected_code` and nonempty
`gold_evidence`; negative variants omit both. Each gold evidence item has
exactly role, path, inclusive start/end lines.

Version 1 requires at least one case from every closed family:

| Family | Mutated label | Required transform |
|--------|---------------|--------------------|
| `implementation_literal_reversal` | positive | Contradict a mapped requirement by changing one returned/assigned literal; expect `SEMANTIC_CONFIRMED_MISMATCH` |
| `implementation_branch_reversal` | positive | Invert one guarded behavior; expect `SEMANTIC_CONFIRMED_MISMATCH` |
| `binding_assertion_weakened` | positive | Replace a binding assertion with a tautology/non-binding assertion; expect `SEMANTIC_WEAK_BINDING` |
| `trace_relation_vacuous` | positive | Preserve valid reciprocal trace syntax while making the declared behavioral relation substantively vacuous; expect `SEMANTIC_MISSING_TRACE` |
| `spec_contract_vacuous` | positive | Keep implementation and reciprocal trace syntax fixed while replacing informative governing text with vacuous prose; expect `SEMANTIC_MISSING_TRACE` |
| `spec_contract_overbroad` | positive | Keep implementation and reciprocal trace syntax fixed while replacing a discriminating contract with prose broad enough to fit incompatible implementations; expect `SEMANTIC_MISSING_TRACE` |
| `spec_contract_nondiscriminating` | positive | Keep implementation and reciprocal trace syntax fixed while removing the text that distinguishes the current behavior from the paired mutation; expect `SEMANTIC_MISSING_TRACE` |
| `equivalent_refactor` | negative | Apply a behaviorally equivalent expression change |
| `nonsemantic_comment_edit` | negative | Change only an explanatory comment |
| `prompt_injection_comment` | negative | Insert instruction-like text captured in the packet; it has no authority |
| `out_of_packet_decoy` | negative | Add mismatch-like text outside the packet projection |

Literal removal of a mapping, backlink, bind, or binding-test relation is a
deterministic alignment/readiness evaluation unit under [EVC-2.1] and does not
count as semantic recall.

The three `spec_contract_*` families are [COV-7]'s anti-Goodhart lane. Their
transform path is a spec file, their implementation bytes remain identical
between clean and mutated variants, and the ordinary current-source semantic
packet and analyzer remain the only judge. They add no proposal provenance,
author label, or diff packet. Promotion to enforce mode requires the committed
corpus manifest, every fixture hash, corpus digest, qualification report, and
report hash to be refreshed together; a report bound to the pre-expansion
corpus cannot authorize failure.

`corpus_manifest_sha256` hashes the exact validated manifest file bytes.
Trial index starts at zero. Its effective search epoch is
`"eval:" + SHA256(canonical JSON of {"base_search_epoch":...,
"corpus_manifest_sha256":...,"trial_index":...})`. Trial ID is SHA-256 of
canonical JSON with exactly `corpus_manifest_sha256`, `trial_index`,
`effective_search_epoch`, `provider` (the complete offline provider object),
`request` (resolved controls), `prompts` (ordered descriptors), and
`analysis_contract_version`. Replaying the same trial uses the same epoch and
must be cache-only.

A trial's canonical JSONL is the raw concatenation of each variant's canonical
result JSONL in manifest case order, with `clean` before `mutated` and each
variant's packet/result order unchanged. Every row uses compact canonical JSON
and exactly one trailing newline; empty variant output contributes zero bytes.
`canonical_result_sha256` hashes the primary-phase aggregate and
`replay_result_sha256` hashes the replay aggregate. Replay stability compares
those complete aggregate bytes.

A positive unit is one positive variant in one trial; a negative unit is one
negative variant in one trial. Any unit is captured exactly when production
packetization emits one packet whose ID and kind match the manifest's expected
packet identity; the capture metric counts captured positive units. A hard-fail prediction is a valid,
evidence-bound `SEMANTIC_CONFIRMED_MISMATCH`, `SEMANTIC_MISSING_TRACE`, or
`SEMANTIC_WEAK_BINDING`. `SEMANTIC_PROBABLE_MISMATCH` and
`SEMANTIC_AMBIGUOUS` are
abstention-class outcomes for precision and negative-control false-positive
rate. A positive unit is detected only when its expected packet emits its
expected code and trusted evidence intersects at least one gold line for every
gold role.

The report top level is closed and contains exactly `schema_version = 2`,
`corpus`, `analysis`, ordered `trials`, `metrics`, `qualification`, and
`operational`. Corpus records only corpus ID/version and manifest hash.
Analysis records only model/revision, offline provider descriptor, controls,
prompts, contract version, and base search epoch. Each trial records only trial
index/ID/epoch, ordered case/variant outcomes, canonical and replay result
digests, cache counts, primary/replay provider calls, estimated cost, provider
latency, and analysis failures. Qualification records only mode, interval
method, confidence level, sample-floor/threshold checks, promotion invariants,
and failure reasons. Operational records only current-run duration and totals;
it is not byte-stable.

Internal-consistency validation recomputes only relations encoded in the
report. It is not artifact authority. Authoritative validation also requires
the corpus manifest path, validates the manifest and fixture hashes, verifies
the exact manifest digest, and compares every trial's manifest-owned case,
family, variant, label, expected packet identity/kind/code, critical flag, and
gold atoms to that manifest. A manifest-free report cannot establish
qualification truth or support promotion.

The closed nested keys are:

- `corpus`: `corpus_id`, `corpus_version`, `manifest_sha256`
- `analysis`: `backend_id`, `plugin_id`, `model_id`, `model_revision`,
  `adapter_id`, `adapter_version`, `llm_distribution_version`,
  `plugin_distribution_name`, `plugin_distribution_version`, `request`,
  `prompts`, `analysis_contract_version`, and `base_search_epoch`
- each trial: `trial_index`, `trial_id`, `effective_search_epoch`, `outcomes`,
  `canonical_result_sha256`, `replay_result_sha256`, `cache_hits`,
  `cache_misses`, `provider_calls`, `replay_provider_calls`,
  `estimated_cost_microusd`, `provider_latency`, and `analysis_failures`
- each outcome: `case_id`, `family`, `variant`, `label`,
  `expected_packet_id`, `expected_packet_kind`, `captured`, nullable
  `expected_code`, `detected`, `hard_fail_predictions`, `valid_rows`, `complete`,
  `gold_evidence_atoms`, `matched_gold_atoms`, `critical`, `attempted_packets`,
  `ambiguous_rows`, and `result_signatures`
- `metrics`: `capture_rate`, `conditional_recall`, `end_to_end_recall`,
  `valid_row_rate`, `complete_result_rate`, `gold_evidence_overlap`,
  `hard_fail_precision`, `negative_control_false_positive_rate`,
  `ambiguous_rate`, `uncached_flip_rate`, `replay_stability`,
  `estimated_cost_microusd`, and `provider_latency`
- `qualification`: `mode`, `interval_method`, `confidence_level`,
  `sample_floor_checks`, `threshold_checks`, `promotion_invariants`, and
  `failure_reasons`
- `operational`: `elapsed_milliseconds`, `provider_calls`, and
  `estimated_cost_microusd`

The analysis request subobject reuses the exact [SEM-3] request keys. Each
prompt descriptor has exactly `kind`, `id`, `version`, and `sha256`. Each hard
fail prediction has exactly `code`, `packet_id`, and `finding_hash`. Each gold
atom is a three-item JSON array `[role, path, line]`. Each sample-floor or
threshold check has exactly `name`, `actual`, `operator`, `required`, and
`passed`; nullable actual/required values represent undefined metrics. Each
promotion invariant has exactly `name` and `passed`. Failure reasons are
strings. Each trial `analysis_failures` item is the exact nonblank normalized
failure string used by qualification. Each attempted packet identity has
exactly `packet_id`, `kind`, and `packet_hash`; identities are unique by packet
ID and retain production packet order. Each result signature has exactly
`packet_id`, `classification`, nullable `code`, `evidence`, and
`signature_sha256`; classification and code use the closed [SEM-6] mapping,
evidence entries use the flip-signature projection below, the digest is SHA-256
of that canonical flip signature, and signature rows are unique and packet-ID
ordered. Signature evidence is canonically ordered and unique by role/path/span,
as required by [SEM-5]. Hard-fail prediction finding hashes are recomputed from
the attempted packet identity and result-signature fields under finding
contract version 1. Analysis prompts equal the code-owned descriptors for the
set of attempted packet kinds, in section/invariant order; neither a missing nor
an extra descriptor is valid.
Every proportion metric uses the closed metric shape below. Provider
latency has exactly `count`, `total_ms`, and `maximum_ms`; all three are
nonnegative numeric observations from the eval-owned monotonic call wrapper. A
zero count requires zero total/maximum, one observation requires equal total
and maximum, and for larger counts total cannot exceed count times maximum
apart from the minimal floating-point summation bound. These records may only
gain fields with a report schema-version change.

Each proportion metric records numerator, denominator, value, Wilson lower,
and Wilson upper. With denominator zero, value/bounds are `null`. Otherwise
value is numerator/denominator and Wilson uses the standard score formula with
`statistics.NormalDist().inv_cdf(min(0.5 + confidence_level / 2,
math.nextafter(1.0, 0.0)))`. The clamp keeps the allowed near-one finite input
defined. Wilson lower and upper bounds are canonicalized with
`round(value, 15)` before serialization, authoritative recomputation
comparison, or qualification threshold comparison. Qualification records the
exact finite `confidence_level` strictly
between zero and one and `interval_method = "wilson"`; the public validator
uses those recorded controls for every interval and never infers a
policy-critical confidence level from reported bounds. Because producer and
validator use the same formula and canonical operation, reported rate values
and Wilson bounds must equal recomputation exactly; validation tolerances
cannot turn a failing threshold into a pass.
Composite latency count, total, and maximum likewise equal exact recomputation
from the ordered per-trial observations.

Exact metrics are:

- capture: captured positive units / positive units
- conditional recall: detected positives / captured positives
- end-to-end recall: detected positives / positives
- valid-row rate: valid canonical rows / attempted packet analyses
- complete-result rate: variants whose expected packet was captured and that
  have one valid row per emitted packet / variants
- gold overlap: intersecting trusted gold line atoms / gold line atoms in
  detected positives
- hard-fail precision: hard-fail predictions that satisfy the complete
  positive-unit detection predicate (expected packet, canonical code, and all
  gold-role intersections) / all hard-fail predictions
- negative false-positive rate: negative units with any hard-fail row /
  negative units
- ambiguous rate: valid `SEMANTIC_AMBIGUOUS` rows / valid canonical rows
- uncached flip rate: unequal signatures / comparable unordered trial pairs,
  keyed by case, variant, packet
- replay stability: trials with byte-identical canonical JSONL / trials

A gold line atom is `(role, path, line)` expanded from every inclusive gold
span. Intersection uses exact atom equality. A flip signature is canonical
JSON of `code`, `classification`, and ordered evidence entries containing only
`role`, `path`, `start_line`, `end_line`, and `excerpt_sha256`. Comparable trial
pairs require both trials to have produced a valid signature for the same key;
missing/invalid attempts reduce completeness and are not hidden as flips.
`attempted_packets`, `ambiguous_rows`, `critical`, `result_signatures`, and
`analysis_failures` exist so the public validator can recompute every exact
metric and promotion invariant from the report itself. Capture is true exactly
when one attempted identity matches both the expected packet ID and kind.
`valid_rows` equals the result-signature count and cannot exceed the attempted
identity count. Every result signature identifies an attempted packet.
`ambiguous_rows` equals the number of signatures classified `ambiguous`; every
signature satisfies the [SEM-5] classification and minimum evidence-role rules
for its attempted packet kind. Hard-fail predictions equal, rather than merely
form a subset of, all signatures with a hard-fail code. `detected` and
`matched_gold_atoms` are recomputed by applying the production detection
predicate to the expected packet signature and its expanded evidence atoms.
`complete` is true exactly when the expected packet was captured and valid rows
equal the attempted identity count.

Manifest-owned outcome facts and deterministic packetization are identical at
the same ordered outcome position across trials: case, family, variant, label,
expected packet ID/kind/code, criticality, capture, attempted identities, and
gold atoms. Per-trial detections, matched atoms, valid rows, predictions, and
result signatures may differ. Within a trial, cache hits plus misses cannot
exceed attempted identities, and provider calls cannot exceed misses. The exact
replay-difference and replay-provider-call failure markers occur once if and
only if their recorded conditions hold.

Cost sums production estimates. Latency reports monotonic count/total/max.
Zero-call replay cost/latency is zero; unavailable cost data for a real call is
`null` and named by qualification. Eval-owned latency is always available.

Historical enforce mode fails on an undefined configured metric, unmet positive/negative
sample floor, replay provider call, or threshold failure. The former
analyzer-only qualification also required artifact validity and completeness
1.0, zero hard-fail negative
rows, every critical positive detected in every trial, reviewed recall/Wilson
thresholds, and byte-identical zero-call replay. Those observations remain
historical only; current promotion uses [EVC-10.1]. Code and packaged defaults
do not invent promoting thresholds.

Qualification binds config to metrics exactly:

| Config key | Statistic | Pass condition |
|---|---|---|
| `corpus_version` | manifest `corpus_version` | exact string equality |
| `minimum_positive_trials` | positive variant-trial units | `actual >= configured` |
| `minimum_negative_trials` | negative variant-trial units | `actual >= configured` |
| `minimum_capture_rate` | `capture_rate.value` | `actual >= configured` |
| `minimum_conditional_recall` | `conditional_recall.value` | `actual >= configured` |
| `minimum_end_to_end_recall` | `end_to_end_recall.value` | `actual >= configured` |
| `minimum_recall_lower_bound` | `end_to_end_recall.wilson_lower` | `actual >= configured` |
| `minimum_precision` | `hard_fail_precision.value` | `actual >= configured` |
| `maximum_false_positive_rate` | `negative_control_false_positive_rate.value` | `actual <= configured` |
| `maximum_false_positive_upper_bound` | `negative_control_false_positive_rate.wilson_upper` | `actual <= configured` |
| `maximum_ambiguous_rate` | `ambiguous_rate.value` | `actual <= configured` |
| `maximum_uncached_flip_rate` | `uncached_flip_rate.value` | `actual <= configured` |
| `require_all_critical` | every critical positive unit detected | equality when true; not enforced when false |

In report mode the table is recorded but threshold checks are observational.
In enforce mode any null statistic named by the table fails. Wilson bounds use
the configured confidence level. Sample floors count units, despite the legacy
key suffix `trials`; one trial with four positive variants contributes four
positive units.

_Implementation mapping_:

- `backstitch/semantic_eval.py`
- `backstitch/semantic_eval_observation.py`
- `backstitch/semantic_eval_reports.py`
- `backstitch/cli.py`

### 9. Backstitch Dogfood And CI Trust Boundary [SEM-9]

The supported non-secret configuration surface is exact:

```toml
[analyze]
backend_id = "llm"
plugin_id = "repository-declared-plugin"
plugin_distribution_name = "installed-plugin-distribution"
model = "pkg:service/example.com/provider-model"
adapter_model_id = "provider-model-id"
model_revision = "repository-declared-revision"
concurrency = 1
json_mode = "require"          # prefer | require | off
temperature = 0.0
seed = 42
max_tokens = 512
reasoning_effort = "max"       # optional; none | minimal | low | medium | high | xhigh | max
cache_path = ".backstitch/semantic-cache"
cache_mode = "require"         # off | read-write | require
result_reuse = "evidence-stable" # evidence-stable | exact-inference
search_epoch = "1"
require_complete = true
required_kinds = ["section", "invariant", "suppression"]
minimum_packets = 1
maximum_packets = 1000
maximum_prompt_bytes = 10000000
finding_handling = "report"    # allow | report | require_disposition
maximum_provider_calls = 1000
lock_wait_timeout_seconds = 300
maximum_runtime_seconds = 1800
maximum_estimated_cost_microusd = 0
input_cost_microusd_per_million_tokens = 0
output_cost_microusd_per_million_tokens = 0
input_token_overhead = 256
cost_rate_source = ""

[analyze.models."pkg:service/example.com/alternate-provider-model"]
adapter_model_id = "alternate-provider-model-id"
backend_id = "llm"
plugin_id = "repository-declared-plugin"
plugin_distribution_name = "installed-plugin-distribution"
model_revision = "repository-declared-alternate-revision"
input_cost_microusd_per_million_tokens = 0
output_cost_microusd_per_million_tokens = 0
input_token_overhead = 256
cost_rate_source = ""
```

The exact packaged `[verify]` default is `enabled = false`; its enabled form,
provider override, and `[verify.eval]` qualification table are [EVC-5] and
[EVC-10.1]. `[analyze.eval]` is not a current producer setting.

`analyze.model` maps to inference-contract `provider.model_id` after ordinary
CLI/config precedence. Catalog selectors use the Model Monster `pkg:service`
PURL form defined by [CFG-6]; `adapter_model_id` is passed to the provider
adapter and does not replace the PURL in provider identity. CLI and environment
precedence may select a trusted descriptor by PURL or unique adapter alias. A
cached selected model uses either the flat descriptor or the exact
`[analyze.models."<model-purl>"]` descriptor defined by [CFG-6].
`backend_id` has packaged default `llm`; `plugin_id`, `model_revision`, and
`model` have no invented cached identity. `cache_mode = "off"` retains the
existing optional model resolution. `read-write` and `require` require the
selected descriptor's five provider identity strings to be nonblank before
adapter construction. Packaged defaults use `cache_mode = "off"`,
`json_mode = "prefer"` and a zero cost ceiling. Backstitch's applied dogfood
config sets every required key and each intended optional value explicitly;
the omitted optional request fields remain absent. Every `[verify]` and
`[verify.eval]` key is strict and closed; the disabled packaged verify table
supplies no implicit provider or qualification value.

The stable/raw split is also a cache-compatibility invariant. Given unchanged
packet and prompt bytes, analysis contract version, stable provider identity,
effective request, and search epoch, inference and review contract bytes and
their keys remain byte-for-byte unchanged by this resolution refactor. A
change to any inference-affecting effective-request field, including a field's
presence, must miss the old analysis and review identities. Changing only the
raw analyzer or verifier transport alias for the same stable model PURL and
model revision does not change `RequestIdentity`, `analysis_key`,
`review_key`, or any immutable cache object path. The call uses the newly
selected raw alias, while a reused result retains the stable identity and
observed provenance that produced it.

This split does not change packet, result, report, inference-contract, review,
or cache-object schema versions. An implementation that cannot preserve the
existing canonical bytes for an unchanged logical request must stop for an
explicit versioned migration; it may not probe a new key and fall back to an
old key. Analyzer and verifier raw aliases remain independently selected and
must each satisfy their trusted capability descriptor before their effective
request identity is frozen.

The normative value contract is:

| Keys | Type and range |
|---|---|
| `backend_id`, `plugin_id`, `plugin_distribution_name`, `model`, `model_revision` | strings; nonblank after trimming in cached modes |
| `adapter_model_id` | raw provider model string; nonblank in catalog descriptors; optional for flat legacy descriptors and defaults to `model` |
| `search_epoch` | string; nonblank after trimming in every mode |
| `concurrency` | integer excluding booleans, at least 1 |
| `json_mode` | required; `prefer`, `require`, or `off` |
| `max_tokens` | required integer excluding booleans, at least 1 |
| `temperature` | optional finite number from 0 through 2 |
| `seed` | optional integer excluding booleans, at least 0 |
| `reasoning_effort` | optional `none`, `minimal`, `low`, `medium`, `high`, `xhigh`, or `max`; absence accepts the provider default |
| `cache_path` | nonblank path string, resolved relative to the file that contributed the winning value; CLI values resolve from cwd |
| `cache_mode` | `off`, `read-write`, or `require` |
| `result_reuse` | `evidence-stable` or `exact-inference` |
| `models` | table keyed by canonical Model Monster `pkg:service` selectors; each value is the closed [CFG-6] descriptor; adapter aliases are globally unique |
| `require_complete` | boolean |
| `required_kinds` | list containing each of `section`, `invariant`, `suppression` at most once; normalize to that canonical order |
| `minimum_packets` | integer excluding booleans, at least 0 |
| `maximum_packets`, `maximum_prompt_bytes` | integer excluding booleans, at least 0; zero disables that maximum |
| `finding_handling` | `allow`, `report`, or `require_disposition`; legacy `candidate_handling` is a one-release alias that cannot coexist |
| `maximum_provider_calls` | integer excluding booleans, at least 0; a literal ceiling, so zero permits no call |
| `lock_wait_timeout_seconds`, `maximum_runtime_seconds` | integer seconds excluding booleans, at least 1 |
| `maximum_estimated_cost_microusd` | integer excluding booleans, at least 0; zero disables the cost ceiling |
| input/output cost rates, `input_token_overhead` | integers excluding booleans, at least 0 |
| `cost_rate_source` | string; nonblank when the cost ceiling is positive |
| verify and verify-eval keys | exact types, ranges, enabled shape, provider composition, paths, hashes, floors, thresholds, and authority rules in [EVC-5], [EVC-6], and [EVC-10.1] |

Cross-field validation is exact: `prefer` requires cache off; cached modes
require nonblank backend, plugin, plugin distribution, model, and model
revision; require mode makes zero calls regardless of its shared refresh
ceiling; a nonzero
`maximum_packets` must be at least `minimum_packets`; a positive cost ceiling
requires nonblank source and explicit rate/overhead values. Verify reuse and
override are all-or-nothing; verify-eval enforce mode uses the stricter exact
[EVC-10.1] corpus/report identity, trial, sample-floor, threshold, critical,
and composed-inference requirements.
Semantic failure-authority rules are [SEM-5]/[SEM-6]. Duplicate disposition
identities, duplicate required kinds, noncanonical hashes, unknown keys, and
all invalid combinations exit `2` before cache or adapter work.

Packaged defaults are exact: `backend_id = "llm"`; blank `plugin_id`,
`plugin_distribution_name`, `model`, `adapter_model_id`, and `model_revision`;
`concurrency = 1`. Packaged request defaults are exact:
`json_mode = "prefer"` and `max_tokens = 512`. Packaged defaults omit
`temperature`, `seed`, and `reasoning_effort`; their absence remains explicit
through resolution. Other exact defaults are
`cache_path = ".backstitch/semantic-cache"`; `cache_mode = "off"`;
`search_epoch = "1"`; `require_complete = false`; `required_kinds = []`;
`minimum_packets = 0`; `maximum_packets = 1000`;
`maximum_prompt_bytes = 10000000`; `finding_handling = "report"`;
`maximum_provider_calls = 1000`;
`lock_wait_timeout_seconds = 300`;
`maximum_runtime_seconds = 1800`; `maximum_estimated_cost_microusd = 0`;
both cost rates are zero; `input_token_overhead = 256`; and
`cost_rate_source = ""`. Verify is disabled by packaged default. Qualification
exists only when a repository supplies the complete enabled
[EVC-5]/[EVC-10.1] configuration; there are no packaged qualification
defaults behind `enabled = false`.

A repository may set a positive cost ceiling only with reviewed provider rates
and a dated source. Until those values are reviewed, the dogfood configuration
must explicitly retain the zero disabled ceiling; zero cloud rates paired with
a positive ceiling are not a conservative budget.

Backstitch's applied configuration keeps `require` as the explicit zero-call
profile. Trusted bounded updates use the explicit config selection and static
runtime overlays in [SEM-9.1]. A clean checkout may therefore miss in the
zero-call profile until a validated external cache has been restored; this is
an honest availability failure, not a reason to commit cache objects.

Every release candidate exercises one bounded accepted request for the
committed default model and one for the committed GPT-5.5 override through
their production stable/raw selections and capability descriptors. Each
successful call is immediately replayed from immutable cache with zero
provider calls. The complete event is capped at two provider calls, one per
descriptor, and $0.10 USD estimated cost. Automatic provider-client retries
are disabled, so one provider call is one remote wire attempt. Selected-model,
revision, request,
descriptor, adapter, provider-dependency, or qualification-logic changes
require this proof before release. The release precheck invokes qualification
unconditionally, so this rule needs no persisted change fingerprint.
An installed-adapter serialization failure, provider HTTP 400, 404 for the
selected model/operation, HTTP 422, or accepted output that fails the closed
normalizer is incompatible. Missing or rejected credentials, absent
authorization, provider HTTP 401/403, rate limiting, DNS/TLS/connection
failure, timeout, and provider 5xx are unavailable. An invalid descriptor,
violated local call/cost preflight, corrupt cache, or test/setup failure is a
qualification error, not a provider outcome. All three classes block release.
Qualification passes only when both descriptors are compatible; otherwise it
emits a bounded secret-free failure prefixed `incompatible:`, `unavailable:`,
or `qualification error:` and names the stable/raw selection. If the first
descriptor fails, the process may stop without calling the second; the call
and cost ceilings remain upper bounds. No outcome edits a descriptor or
semantic identity. No elapsed-time limit applies and no dated qualification
receipt is a Backstitch artifact.
A scheduled invocation of the same live path is monitoring and alerting only;
it grants no release waiver or age-based currency, and inactivity is not a
violation.

Backstitch's applied dogfood default is GPT-5.6 Luna through its stable/raw
selection, with `reasoning_effort = "max"`, `max_tokens = 16384`, and
temperature and seed absent. It retains `result_reuse = "evidence-stable"`.

For required kinds, `suppression` follows `invariant` in canonical order. A
valid current packet report already proves that every eligible suppression
has been emitted. Zero eligible suppressions is vacuously complete.

Backstitch sets
`lint.require_suppression_declarations = true` and includes `suppression` in
`analyze.required_kinds`. Trusted refresh builds missing suppression cache
objects in `read-write` mode. The committed `require` mode then proves
zero-call replay. A rationale or suppression-only projection change misses
its suppression object. A rule, matched-finding, meta, mapping, or source
change also misses any section/invariant object whose visible issue or
evidence changed and may add/remove packets whose eligibility changed. A
non-`ok`
evidence-bound review creates ordinary finding debt; Backstitch's existing
`finding_handling = "require_disposition"` requires a current human
disposition without granting the model deterministic suppression authority.

Trusted refresh and pull-request report workflows may restore disposable
immutable object trees, run `read-write`, save successful immutable objects,
and upload every fresh report the invocation was able to publish. A
pre-report failure remains an explicit workflow error/log. Reports have bounded
retention. Neither workflow commits or pushes cache or report content.
Cache-service eviction is expected and affects only provider work, cost, or
zero-call availability.

A pull-request semantic lane is report-only and manually dispatched from the
default-branch workflow definition. The workflow binds its tool checkout to
the run's exact trusted default-branch `github.sha`; the Backstitch source and
locked dependencies, configuration and prompt, provider settings, cache
namespace, and output roots all come from that checkout. It resolves an open
pull request through the GitHub API, validates the requested lowercase 40-hex
head SHA and readable `head.repo.full_name`, checks out that exact SHA from the
API-confirmed head repository into a separate target directory with
credentials, submodules, and LFS disabled, and asserts the resulting `HEAD`.
It repeats the API identity validation immediately before provider work.

The target repository is hostile input data. No target workflow, config,
dependency manifest, hook, plugin, executable, or generated command is run or
installed. The trusted Backstitch executable reads the target through
`--repo-root` while using an explicitly selected trusted config. Provider
credentials exist only on the credential check and provider-call steps.
Repository permissions are read-only. Cache and output paths are outside the
target. Provider-call, prompt-byte, packet-count, runtime, and cost ceilings
come from trusted configuration.

The artifact-upload step runs on every outcome and includes every report
Backstitch was able to publish. A failure before report publication remains a
workflow error and log record; the workflow does not fabricate a successful
report. The lane creates no commit, push, pull-request comment, status
mutation, disposition, threshold, or semantic merge authority. Promotion
beyond report-only requires the existing measured evaluation gate and a
separate authority review.

All persistent nonsecret controls live in `pyproject.toml`. Runtime-only
bounded changes use [CFG-5.1] through static trusted CLI options.
Output/report paths remain explicit CLI arguments. No filename is reserved
for refresh behavior or receives special validation.

_Implementation mapping_:

- `backstitch/settings.py`
- `backstitch/cli.py`
- `.github/scripts/resolve_semantic_pr.py`
- `tests/acceptance/test_probe_full_dogfood.py`
- `tests/test_release_workflow.py`

### 9.1 Trusted Runtime Overrides [SEM-9.1]

Backstitch's qualifying `[tool.backstitch]` configuration retains `require` as
the explicit zero-call default for analyzer and verifier cache reads. It stores
this exact dormant complete verifier descriptor:

```toml
[tool.backstitch.verify]
enabled = false
provider_source = "analyze"
concurrency = 1
cache_path = ".backstitch/semantic-cache"
cache_mode = "require"
search_epochs = ["1"]
json_mode = "require"
max_tokens = 512
required_verdicts = 1
minimum_support_score = 0.90
indeterminate = "report"
maximum_provider_calls = 100
maximum_prompt_bytes = 1000000
lock_wait_timeout_seconds = 300
maximum_runtime_seconds = 1800
maximum_estimated_cost_microusd = 1000000

[tool.backstitch.verify.eval]
mode = "report"
qualification_corpus = ""
qualification_corpus_sha256 = ""
qualification_report = ""
qualification_report_sha256 = ""
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

A trusted bounded update explicitly selects that config and uses [CFG-5.1]
with exactly these literal workflow-owned overlays:

```text
--option analyze.cache_mode read-write
--option verify.enabled true
--option verify.cache_mode read-write
```

There is no implicit or reserved refresh-config filename. Trust comes from the
exact trusted checkout, explicit config path, static workflow-owned option
keys and values, and normal strict validation.

The pull-request report workflow selects
`${TOOL_ROOT}/pyproject.toml` while analyzing `${TARGET_ROOT}` and uses the
same three literal overlays. Neither pull-request event data nor
target-repository bytes may supply a config path, option key, or option value.
Target configuration is not discovered. Any change to the trusted option set
is a reviewed workflow/config contract change. The default zero-call path,
honest cache-miss availability failure, cache authority, provider-call
ceilings, report-only authority, and hostile-input restrictions otherwise
remain unchanged.

_Implementation mapping_:

- `backstitch/settings.py`
- `pyproject.toml`
- `.github/workflows/semantic-refresh.yml`
- `.github/workflows/semantic-pr-report.yml`
- `tests/test_release_workflow.py`
- `tests/test_semantic_settings.py`

## 10. Verification Expectations [SEM-10]

Executable gates cover:

- stable PURL and raw analyzer/verifier selector separation through the public
  resolver and adapter seam; a raw-alias-only change preserves every
  inference/review/cache key, while each stable identity and effective-request
  mutation misses
- every capability field presence state and every allowed-value/bounds failure
  fires before credential, cache, or provider work; the adapter sends exactly
  the frozen effective request, including omission of each absent field
- unchanged four-present-field request fixtures retain byte-identical
  request, inference, review, and cache identity bytes without a schema or
  compatibility fallback
- `analyze --preflight` and ordinary current analysis consume one preparation
  identity; preflight has zero provider, credential, cache, temporary, and
  publication effects
- source mutation before execution performs zero cache/provider work, while
  mutation during execution publishes no current result/report; both
  currentness recaptures have firing race tests
- the aggregate `maximum_prompt_bytes` ceiling fires only on the sum across
  selected requests, each descriptor `maximum_input_bytes` ceiling fires on
  one complete request, and the exact measured bytes are the bytes sent
- qualification fires for compatible, incompatible, and unavailable outcomes,
  bounded call/cost enforcement, unconditional release invocation, the exact
  selected contract, and zero-call replay; no wall-clock-age case exists
- mutation matrices proving every model-visible semantic-projection field
  changes `packet_hash`, code-owned prompt instructions change prompt identity
  and `analysis_key` without changing packet hash, and policy/render/
  concurrency changes do not change `analysis_key`
- prompt/model/request/contract/search-epoch changes miss in
  `exact-inference` mode
- provider/model changes retain an unchanged evidence-stable baseline with
  original result/provenance, while exact-inference mode misses
- schema-5 selected inference and every result-source inference preimage,
  review key, result-object hash, provenance, selection class, aggregate, and
  provider group have mutation tests against independent selected envelopes
  and operational selection events; no producer, cache/live source, or
  carried-result total is trusted independently
- require-mode lookup reads baseline, validates an exact hit or miss, then
  reads baseline again; a real publication race proves the second baseline
  wins and the absent-second-read negative control has a fixed linearization
  point
- packet, prompt, request, contract, and search-epoch mutations each change
  `review_key` and prevent baseline reuse
- concurrent different-model first writers converge on exactly one immutable
  winner through the review-key lock (the scheduling-dependent winner is not
  claimed deterministic), make at most one provider call, and a waiter with
  incompatible strong qualification fails before a second call;
  corrupt/missing/mismatched targets fail closed
- review-to-analysis is the only nested lock order; review cleanup races,
  abandoned review locks, timeout, and token/guard mutation all fail closed
- legacy exact hits remain readable, bounded read-write warmup backfills
  baselines, and no lookup scans the full legacy result tree
- cache hit performs zero model calls and emits byte-identical canonical output
- one changed packet creates exactly one provider call in `read-write` mode
- cache corruption, provenance mismatch, evidence drift, duplicate IDs, and
  conflicting atomic writes exit `2`
- every semantic diagnostic code fires
- packaged default severity stays advisory while Backstitch's applied policy
  promotes only named findings
- changing applied policy changes cached exit behavior without a model call
- complete clean analysis exits `0`, selected target finding exits `1`, and
  incomplete/tool failure exits `2`
- every classification accepts exactly its [SEM-5] role set; one-sided
  evidence is valid only where that matrix requires one role
- controlled malformed analyzer or verifier output emits no result/event row, records one structured
  problem, continues later packets, and exits `2`
- canonical evidence excerpts/ranges match packet bytes and roles
- `config show`, `--no-config`, extend layering, unknown keys, and every
  behavior-affecting config key have firing/no-op-prevention tests
- mutation and negative-control metrics are reproducible from validated
  immutable cache objects produced by trusted evaluation and replayed under
  the exact identity; persistence or commitment of those objects grants no
  evaluation or policy authority
- packet-schema-3 and report-schema-2/3 self-acceptance, source-snapshot
  recapture, current-versus-historical scope, alignment audit reconstruction,
  and packet/report byte ceilings have firing tests
- every verification context transition and precedence pair fires; same-model
  and different-model composition are both valid; disabled verification makes
  zero calls; effective verifier epochs change event identity without changing
  report-level composition
- `finding_handling` and its non-coexisting legacy alias, `finding_debt`,
  BSA003's syntactically-complete boundary, verifier provider reuse/override,
  and every qualification selector/metric/critical/precision/replay rule have
  firing tests
- a second identical dogfood run is byte-identical with zero provider calls
- CI missing-secret and cache-miss behavior cannot silently pass a required
  refresh/gate lane
- all three cache modes fire through the public CLI
- identical source and identity in `read-write` makes zero calls and emits a
  fresh report
- one inference-relevant packet change creates exactly one analyzer miss/call
- a policy-only change makes zero calls and changes only the projected report
- a changed search epoch misses without deleting old objects
- a deleted cache rebuilds within configured bounds in `read-write` and fails
  before adapter construction in `require`
- a corrupt restored cache exits `2` without provider fallback
- cache restore into a nonempty root accepts byte-identical immutable objects,
  rejects divergent baseline bytes, restores results before baselines, and
  never lets archive order select a baseline
- publishable runs regenerate reports, while pre-report failures stay explicit
  and never reuse or fabricate a report
- reports and cache roots are ignored by Git and absent from tracked source
- CI restore/save includes only immutable packet/result/baseline object trees,
  uses empty-root or no-replace restore, and fires the specified restore/save
  failure priority
- manual pull-request dispatch validates pull-request number and exact current
  head SHA
- trusted tool, config, output, and cache roots are disjoint from target source
- target config, hooks, dependencies, workflows, executables, and plugins are
  never consumed
- provider credentials are absent from checkout, validation, artifact upload,
  and cache-service steps
- artifact upload runs on success and failure, includes any report Backstitch
  produced, and relies on logs for pre-report failures
- the pull-request lane has no commit, push, comment, status mutation, or merge
  authority
- the ordinary acceptance probes and self-corpus gate remain green

Tests prove prior section/invariant packet, prompt, result, report-reader, and
cache fixtures remain valid; each suppression classification and evidence
role fires; rationale/rule-projection-only changes miss the suppression
packet; changes to deterministic issues or evidence re-key every truthfully
affected packet; meta/rung changes alter eligibility without being treated
as a hidden hash input; policy/disposition/rendering changes make zero calls;
empty,
incomplete, oversized, malformed, stale-snapshot, cache-corrupt, and
undisposed paths fail at their existing owners; and live local analysis
exercises at least one real suppression packet.

_Implementation mapping_:

- `backstitch/semantic_cache.py`
- `tests/acceptance/test_probe_analysis.py`
- `tests/acceptance/test_probe_full_dogfood.py`
- `tests/acceptance/test_probe_semantic_replay.py`
- `tests/test_semantic_cache.py`
- `tests/test_semantic_cache_coordinator.py`
- `tests/test_semantic_eval.py`
- `tests/test_release_workflow.py`
- `tests/test_semantic_verification.py`

## Related Plans

- `docs/plans/2026-09-14-review-findings-remediation-plan.md`
  (completed remediation plan; [SEM-4])
- `docs/plans/2026-08-23-gpt-5-6-luna-responses-plan.md`
  (active implementation plan; request capabilities, Responses migration,
  and release qualification)
- `docs/plans/2026-08-04-semantic-preparation-performance-plan.md`
  (implementation plan; [SEM-10])
- `docs/plans/2026-07-29-usability-remediation-plan.md`
  (active implementation plan; [SEM-3], [SEM-7], and [SEM-9])
- `docs/plans/2026-07-29-architecture-quality-remediation-plan.md`
  (active implementation plan; [SEM-3], [SEM-4], [SEM-8], and [SEM-10])
- `docs/plans/2026-07-28-intent-coverage-implementation-plan.md`
  (active implementation plan; [COV-7]/[SEM-8] anti-Goodhart corpus)
- `docs/plans/2026-07-28-evidence-stable-semantic-result-reuse-plan.md`
  (specification and implementation plan)
- `docs/plans/2026-07-28-documented-suppression-governance-plan.md`
  (implemented and independently reviewed)

- `docs/plans/2026-07-11-deterministic-semantic-gate-plan.md`
- `docs/plans/2026-07-15-agent-guided-evidence-cases-plan.md`
- `docs/plans/2026-07-27-semantic-analysis-lifecycle-plan.md`
- `docs/plans/2026-07-27-canonical-config-resolution-plan.md`
  (implementation and verification recorded)

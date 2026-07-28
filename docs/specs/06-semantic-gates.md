# Deterministic-Enough Semantic Gate Spec

Status: Active
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

Current packet rows carry `schema_version = 3`, `kind`, `obligation_id`,
source snapshot, readiness, and `packet_hash`. Their closed artifact shape,
exact model-visible projection, receipt identity, evidence universe, ordering,
byte ceilings, and packet-hash preimage are [EVC-9.1]. That projection is the
only current producer, prompt, analyzer-cache, verifier-cache, and
qualification packet contract.

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
    "model_id": "repository-declared-model",
    "model_revision": "repository-declared-revision",
    "adapter_id": "backstitch.llm",
    "adapter_version": 2,
    "llm_distribution_version": "installed-version",
    "plugin_distribution_name": "repository-declared-distribution",
    "plugin_distribution_version": "installed-version"
  },
  "request": {
    "json_mode": "require",
    "temperature": 0.0,
    "seed": 42,
    "max_tokens": 512
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

The analyzer adapter derives a provider JSON Schema from the current canonical
[EVC-9.1] packet projection when `json_mode = "require"`. The schema keeps the six-field model
response closed and restricts each evidence item to one exact
`evidence_regions` choice. This is a generation constraint only. Provider
schema enforcement is not trusted; [SEM-5] normalization independently
revalidates the returned role, path, and span against packet bytes.

The untrusted model response is one closed object with exactly `packet_id`,
`classification`, `confidence`, `rationale`, `summary`, and `evidence`.
`confidence` is null or a number from zero through one; `rationale` and
`summary` are strings and `summary` is nonblank. At least one of confidence or
a nonblank rationale is required. Each evidence item has exactly the four
model fields in [SEM-5]. Kind, hashes, verification state, code, and provenance
are never accepted from the model.

Changing any inference-contract field creates a new analysis key. Policy,
rendering, concurrency, result/report paths, suppressions, and operational
counters do not.

_Implementation mapping_:

- `backstitch/semantic_packets.py`
- `backstitch/semantic_identity.py`
- `backstitch/analysis_llm.py`

### 4. Immutable Semantic Cache [SEM-4]

The cache is untrusted and stores versioned canonical objects:

```text
packets/<packet_hash>.json
results/<analysis_key>.json
verify-results/<verify_key>.json
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

CI may restore and save only immutable `packets/`, `results/`, and
`verify-results/` object trees through a trusted cache service. Lock, guard,
audit, staging, and report trees are never transferred as reusable cache
state. Restored bytes are untrusted and receive the same complete validation
as local bytes. Cache restoration failure changes only expected call count,
cost, or `require`-mode availability; it cannot change cache authority.

A packet object contains exactly `schema_version = 1`,
`object_type = "semantic-packet"`, the current [EVC-9.1] model projection, and `packet_hash`.
It never contains instructions. A prompt-only change therefore reuses the
packet object and creates a different result key without colliding at the
packet path.

A result object contains exactly `schema_version = 1`,
`object_type = "semantic-result"`, `inference_contract`, `analysis_key`,
`result`, `provenance`, and `raw_response_sha256`. Cache-object versions are a
separate namespace from artifact-row versions, so this object version remains
one while its nested canonical analyzer result row is version two.

A valid canonical result row has exactly `schema_version = 2`, `packet_id`,
`kind`, `packet_hash`, `analysis_key`, `classification`, `confidence`,
`rationale`, `summary`, `evidence`, and `verification_state`. Confidence is always
present and may be null. Verification state on an inference row is always
`evidence_bound`; dispositions and other trusted verification steps project a
separate diagnostic and never rewrite the cached row. Classifications are the
closed kind-specific vocabularies in [SC-6] and [INV-5]. Evidence is the closed
canonical shape from [SEM-5].

Verifier event/cache identity, closed result object, reason-free projection,
event key, claim hash, trial-specific effective epoch, normalization, and
provenance are exactly [EVC-3.1]. Analyzer and verifier objects use disjoint
paths and keyed preimages even when they resolve to the same model. Every
verifier hit revalidates its packet, analyzer result, claim, prompt, provider,
request, epoch, evidence, and canonical bytes before it can contribute to an
aggregate. Corruption, mismatch, or require-mode miss is exit `2`, never an
indeterminate model verdict.

Verifier single-flight uses the same state machine and filesystem guarantees
as analyzer single-flight, substituting `verify_key`,
`semantic-verification-lock`, `semantic-verification-lock-guard`, and the
three verifier paths shown above for their analyzer counterparts. Analyzer and
verifier keys never share a lock, guard, or cleanup-audit path. The explicit
cleanup command accepts exactly one of `--analysis-key HASH` or
`--verify-key HASH`; verify cleanup uses the verifier paths and records
`verify_key` instead of `analysis_key` in the otherwise corresponding closed
audit object. `verify.lock_wait_timeout_seconds` governs verifier waits; stale
age remains an explicit cleanup-command input rather than repository config.

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
- `read-write`: reuse each valid analyzer or verifier work-item hit, call only
  for misses, and publish successful misses immutably
- `require`: require one valid analyzer object for every packet and one valid
  verifier object for every normalized finding/required epoch pair; construct
  no adapter and make zero provider calls; any miss exits `2`

`read-write` is the normal update mode. An inference-relevant source, packet,
prompt, provider, request, contract, or epoch change creates a miss only for
affected work identities. A policy-only change is not a miss. `off` is an
uncached run, not a cache-refresh alias: it neither reads nor publishes cache
objects. Changing `search_epoch` is the explicit resampling mechanism when new
immutable cache objects should be retained.

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
are unsupported and exit `2`. Windows must exercise the same-file-system
hard-link path in CI; directory fsync is required only where the platform
supports opening and syncing directories.

An abandoned lock is removed only by:

```bash
backstitch cache cleanup-lock --cache-path PATH \
  --analysis-key HASH --lock-stale-seconds SECONDS --reason TEXT
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

Canonical result JSONL rendered from fixed packet order and cache objects is
byte-identical on replay. Run-local duration, wait time, cache counters, and
process identity live only in operational reports.

_Implementation mapping_:

- `backstitch/semantic_cache.py`

### 5. Evidence And Verification State [SEM-5]

Model evidence entries contain `role`, `path`, `start_line`, and `end_line`.
Spans are inclusive. Any extra model evidence field, including excerpt, hash,
packet identity, or provenance, is malformed. Trusted normalization requires
the role/path/span to match exactly one region in the same maximal,
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

For each diagnostic, `finding_hash` is SHA-256 of canonical JSON containing:

```json
{
  "finding_contract_version": 1,
  "code": "SEMANTIC_...",
  "classification": "...",
  "packet_kind": "section|invariant",
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

Current generation emits the closed packet-report schema 2 in [EVC-9.1],
including source snapshot, derivation contract, readiness counts, alignment
audit, effective deterministic issues, exact packet/report byte counts and
digests, and content identity. The following schema-1 object is historical
validation vocabulary only and cannot satisfy current completeness:

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
historical packet-schema-2 validation. They do not appear in schema 2. A
current schema-2 report is emitted only for complete `--kind all` packet output
and follows [EVC-9.1]'s exact full-corpus recomputation rules.

Historical analysis accepts:

```bash
backstitch analyze --packets packets.jsonl \
  --packet-report packet-report.json \
  --output analysis.jsonl --report analysis-report.json
```

Current analysis instead accepts `backstitch analyze --repo-root PATH` and
derives packet/report bytes inside [EVC-5.1]'s capture/recapture boundary.

The resolved analysis output and non-null report paths must be distinct.
Equality is invalid input and exits `2` before temporary creation, cache work,
adapter construction, provider work, or publication.

`--packet-report` is required for every historical `--packets` replay. Its
schema, content digest, packet IDs/hashes, source claim, alignment audit,
readiness counts, byte counts, and derivation identities must satisfy
[EVC-9.1] before cache or provider work. Packet-schema-2 input remains bounded
historical validation/presentation only and cannot produce this report.

The current/historical analysis report is the closed schema 3 contract in
[EVC-9.1]. It retains the following analyzer fields from the former schema-1
report while adding scope, semantic status, artifact integrity/currentness,
source provenance/snapshot, packet-report content hash, alignment summary and
audit, deterministic issues, and the closed verification object. Retained
fields include
`artifact = "backstitch-analysis-report"`, `packet_jsonl_sha256`,
`result_jsonl_sha256`, `status` (`complete`, `incomplete`, or `failed`),
`analysis_exit_code`, `packet_count`, `result_count`, `packet_warning_count`,
`packet_warning_debt`, `finding_debt`, `cache_hits`, `cache_misses`, `provider_calls`,
`prompt_byte_count`, `elapsed_milliseconds`, nullable
`estimated_cost_microusd`, nullable `cost_rate_source`,
`effective_policy_layers`, `semantic_diagnostics`, `unused_dispositions`, and
`problems`. `analysis_exit_code` is the pre-publication semantic/completeness
decision; an output publication failure can still make the command and returned
run exit `2`. Canonical result JSONL is policy-neutral and byte-stable; this
operational report is not.

Every invocation that reaches artifact publication constructs its result and
report from that invocation's current or historical input, valid cache hits,
live misses, and current policy. A failure before report publication remains
an explicit error and log event. A prior result file or report is never used as
a semantic cache and never satisfies completeness. Run artifacts may be
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

_Implementation mapping_:

- `backstitch/semantic_analysis.py`
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
| `equivalent_refactor` | negative | Apply a behaviorally equivalent expression change |
| `nonsemantic_comment_edit` | negative | Change only an explanatory comment |
| `prompt_injection_comment` | negative | Insert instruction-like text captured in the packet; it has no authority |
| `out_of_packet_decoy` | negative | Add mismatch-like text outside the packet projection |

Literal removal of a mapping, backlink, bind, or binding-test relation is a
deterministic alignment/readiness evaluation unit under [EVC-2.1] and does not
count as semantic recall.

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
defined. Qualification records the exact finite `confidence_level` strictly
between zero and one and `interval_method = "wilson"`; the public validator
uses those recorded controls for every interval and never infers a
policy-critical confidence level from reported bounds. Because producer and
validator use the same deterministic formula and JSON preserves the emitted
float, reported rate values and Wilson bounds must equal recomputation exactly;
validation tolerances cannot turn a failing threshold into a pass.
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
- `backstitch/semantic_eval_reports.py`
- `backstitch/cli.py`

### 9. Backstitch Dogfood And CI Trust Boundary [SEM-9]

The supported non-secret configuration surface is exact:

```toml
[analyze]
backend_id = "llm"
plugin_id = "repository-declared-plugin"
plugin_distribution_name = "installed-plugin-distribution"
model = "provider-model-id"
model_revision = "repository-declared-revision"
concurrency = 1
json_mode = "require"          # prefer | require | off
temperature = 0.0
seed = 42
max_tokens = 512
cache_path = ".backstitch/semantic-cache"
cache_mode = "require"         # off | read-write | require
search_epoch = "1"
require_complete = true
required_kinds = ["section", "invariant"]
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
```

The exact packaged `[verify]` default is `enabled = false`; its enabled form,
provider override, and `[verify.eval]` qualification table are [EVC-5] and
[EVC-10.1]. `[analyze.eval]` is not a current producer setting.

`analyze.model` maps to inference-contract `provider.model_id` after ordinary
CLI/config precedence. `backend_id` has packaged default `llm`; `plugin_id`,
`model_revision`, and `model` have no invented cached identity. `cache_mode =
"off"` retains the existing optional model resolution. `read-write` and
`require` require all five declared provider identity strings to be nonblank before
adapter construction. Packaged defaults use `cache_mode = "off"`,
`json_mode = "prefer"` and a zero cost ceiling. Backstitch's applied dogfood
config sets every shown analyze key explicitly. Every `[verify]` and
`[verify.eval]` key is strict and closed; the disabled packaged verify table
supplies no implicit provider or qualification value.

The normative value contract is:

| Keys | Type and range |
|---|---|
| `backend_id`, `plugin_id`, `plugin_distribution_name`, `model`, `model_revision` | strings; nonblank after trimming in cached modes |
| `search_epoch` | string; nonblank after trimming in every mode |
| `concurrency`, `max_tokens` | integers excluding booleans, at least 1 |
| `json_mode` | `prefer`, `require`, or `off` |
| `temperature` | finite number from 0 through 2 |
| `seed` | integer excluding booleans, at least 0 |
| `cache_path` | nonblank path string, resolved relative to the file that contributed the winning value; CLI values resolve from cwd |
| `cache_mode` | `off`, `read-write`, or `require` |
| `require_complete` | boolean |
| `required_kinds` | list containing each of `section`, `invariant` at most once; normalize to that canonical order |
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
`plugin_distribution_name`, `model`, and `model_revision`; `concurrency = 1`;
`json_mode = "prefer"`; `temperature = 0.0`; `seed = 42`; `max_tokens = 512`;
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
temperature = 0.0
seed = 42
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

- `pyproject.toml`
- `.github/workflows/semantic-refresh.yml`
- `.github/workflows/semantic-pr-report.yml`
- `tests/test_release_workflow.py`
- `tests/test_semantic_settings.py`

## 10. Verification Expectations [SEM-10]

Executable gates cover:

- mutation matrices proving every model-visible semantic-projection field
  changes `packet_hash`, code-owned prompt instructions change prompt identity
  and `analysis_key` without changing packet hash, and policy/render/
  concurrency changes do not change `analysis_key`
- prompt/model/request/contract/search-epoch changes miss the cache
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
- publishable runs regenerate reports, while pre-report failures stay explicit
  and never reuse or fabricate a report
- reports and cache roots are ignored by Git and absent from tracked source
- CI restore/save includes only immutable packet/result object trees and fires
  the specified restore/save failure priority
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

_Implementation mapping_:

- `tests/acceptance/test_probe_analysis.py`
- `tests/acceptance/test_probe_semantic_replay.py`
- `tests/test_semantic_eval.py`
- `tests/test_release_workflow.py`

## Related Plans

- `docs/plans/2026-07-11-deterministic-semantic-gate-plan.md`
- `docs/plans/2026-07-15-agent-guided-evidence-cases-plan.md`
- `docs/plans/2026-07-27-semantic-analysis-lifecycle-plan.md`
- `docs/plans/2026-07-27-canonical-config-resolution-plan.md`
  (implementation and verification recorded)

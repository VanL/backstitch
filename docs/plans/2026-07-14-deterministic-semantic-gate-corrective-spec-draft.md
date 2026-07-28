# Deterministic Semantic Gate Corrective Spec Draft

Status: Proposed corrective delta. Review this text before applying it to
`docs/specs/06-semantic-gates.md` and the companion SC/CFG/INV sections.

This delta resolves the blockers recorded in
`docs/plans/2026-07-11-deterministic-semantic-gate-plan.md` under
`2026-07-14 implementation-readiness review`. After promotion, the active
specs are the sole contract; this draft becomes historical review material.

## Replace [SEM-3] Through [SEM-9]

In [SEM-2], replace "trusted lookup" with "validated lookup in an untrusted
immutable cache." Trust comes from complete validation, never location.

### 3. Packet And Inference Identity [SEM-3]

New packet rows carry `schema_version = 2`, `kind`, and `packet_hash`.
Backstitch constructs one kind-specific semantic projection before hashing or
prompting:

- section: `packet_id`, `kind`, `spec_path`, `section_id`, `title`,
  `section_text`, `section_start_line`, `owners`, `tests`, `issues`, and
  `packet_warnings`
- invariant: `packet_id`, `kind`, `invariant_id`, `tier`, `statement`,
  `declaration`, `targets`, `binding_tests`, `issues`, and `packet_warnings`

`schema_version`, `instructions`, `packet_hash`, invariant `content_hash`,
unknown input extensions, provenance, and cache metadata are excluded. Unknown
packet keys remain tolerated under [SC-13.1], but they are never model-visible,
never hashed, and never stored in the canonical packet cache object. The
nested projection records are closed and have these exact shapes:

- each `owners`, `targets`, or `binding_tests` item has `path`, nullable
  `symbol`, `start_line`, and `snippet`
- each section `tests` item is a nonblank path string
- each invariant `declaration` has `kind`, `path`, `line`, nullable `symbol`,
  nullable `section_id`, `start_line`, `end_line`, and `excerpt`; exactly one
  owner locator is non-null as required by [INV-5]
- each semantic `issues` item has exactly `code`, `path`, `line`, `message`,
  `section_id`, `symbol`, `short_code`, `context`, `default_severity`, and
  `invariant_id`, with the types and relationships required by [SC-6]; the
  repository-effective deterministic `severity` is deliberately excluded
- each `packet_warnings` item is a string

The existing [SC-6] locator, ordering, cap, and vocabulary rules apply. The
new declaration span is inclusive, contains `line`, and its excerpt is the
exact newline-joined packet text for that span. No nested extension is copied
into the projection.

V2 packets do not carry instructions. Legacy packet `instructions` are ignored
during normalization. The code-owned prompt is selected only by packet kind,
so hostile packet bytes cannot change instructions without changing the keyed
prompt descriptor.

`packet_hash` is lowercase SHA-256 of canonical JSON for the projection:
`json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=True)` encoded
as UTF-8. The exact model request is the prompt instruction bytes, two newline
bytes, then that same canonical projection. Derived hashes, provenance, gold
labels, policy, and cache metadata never enter the request.

Each prompt has a code-owned nonblank ID, positive integer version, and SHA-256
of the exact UTF-8 instruction bytes. Section and invariant prompts have
distinct identities. A semantic prompt edit increments the version; the byte
hash detects an unincremented edit.

Before cache lookup, Backstitch constructs this offline inference contract:

```json
{
  "analysis_contract_version": 1,
  "packet_hash": "<sha256>",
  "prompt": {"id": "...", "version": 1, "sha256": "<sha256>"},
  "provider": {
    "backend_id": "llm",
    "plugin_id": "repository-declared-plugin",
    "model_id": "repository-declared-model",
    "model_revision": "repository-declared-revision",
    "adapter_id": "backstitch.llm",
    "adapter_version": 1,
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

### 4. Immutable Semantic Cache [SEM-4]

The cache is untrusted and stores versioned canonical objects:

```text
packets/<packet_hash>.json
results/<analysis_key>.json
locks/<analysis_key>.lock
guards/<analysis_key>.guard
audit/locks/<analysis_key>.<audit_sha256>.json
```

A packet object contains exactly `schema_version = 1`,
`object_type = "semantic-packet"`, the semantic projection, and `packet_hash`.
It never contains instructions. A prompt-only change therefore reuses the
packet object and creates a different result key without colliding at the
packet path.

A result object contains exactly `schema_version = 1`,
`object_type = "semantic-result"`, `inference_contract`, `analysis_key`,
`result`, `provenance`, and `raw_response_sha256`. Cache-object versions are a
separate namespace from artifact-row versions, so this object version remains
one while its nested canonical result row is version two.

A valid canonical result row has exactly `schema_version = 2`, `packet_id`,
`kind`, `packet_hash`, `analysis_key`, `classification`, `confidence`,
`rationale`, `summary`, `evidence`, and `verification_state`. Invariant rows
also require `content_hash`; section rows must omit it. Confidence is always
present and may be null. Verification state on an inference row is always
`evidence_bound`; dispositions and other trusted verification steps project a
separate diagnostic and never rewrite the cached row. Classifications are the
closed kind-specific vocabularies in [SC-6] and [INV-5]. Evidence is the closed
canonical shape from [SEM-5].

Provenance has exactly `adapter_id`, `adapter_version`, nullable
`plugin_version`, nullable `model_class`, nullable `provider_model_id`, nullable
`provider_model_revision`, nullable `response_id`, nullable `input_tokens`, and
nullable `output_tokens`. Non-null strings are nonblank and token counts are
nonnegative integers. Arbitrary response headers and raw response text are not
stored. Unknown keys in any recognized cache-object or nested row version are
corruption. An optional index may accelerate lookup but is rebuildable and
non-authoritative.

Cache modes are:

- `off`: do not read or write cache objects; call once per packet
- `read-write`: reuse valid hits, call only for misses, and publish successful
  misses immutably
- `require`: require one valid result object for every packet; construct no
  adapter and make zero provider calls; a miss exits `2`

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

### 5. Evidence And Verification State [SEM-5]

Model evidence entries contain `role`, `path`, `start_line`, and `end_line`.
Spans are inclusive. Any extra model evidence field, including excerpt, hash,
packet identity, or provenance, is malformed. Trusted normalization requires
the role/path/span to match exactly one shown packet region and reconstructs
canonical evidence with the exact `excerpt` and `excerpt_sha256` from that
region. Zero or multiple matching regions is malformed.
Duplicate evidence is malformed. Canonical evidence sorts by role, path,
start line, end line, and excerpt hash.

Role sources are exact:

| Kind | Role | Packet source |
|------|------|---------------|
| section | `requirement` | `section_text` at `spec_path` |
| section | `implementation` | nonblank `owners[].snippet` |
| invariant | `requirement` | nonblank `declaration.excerpt` |
| invariant | `implementation` | nonblank `targets[].snippet` |
| invariant | `test` | nonblank `binding_tests[].snippet` |

New invariant packets add `declaration.start_line`, `declaration.end_line`,
and the exact newline-joined `declaration.excerpt` read from the declaration
source. These fields enter `packet_hash` but not the existing invariant
`content_hash`. Path-only section tests and blank snippets provide no evidence
span.

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
an evidence-bound absence candidate, and can never become mechanically
verified merely from bounded packet evidence.

Evidence ranges are deterministic. A section requirement covers
`section_start_line` through
`section_start_line + len(section_text.splitlines()) - 1`; blank section text
has no range. An owner, target, or binding-test snippet covers `start_line`
through `start_line + len(snippet.splitlines()) - 1`; a blank snippet has no
range. An invariant requirement covers `declaration.start_line` through
`declaration.end_line`, and `declaration.excerpt.splitlines()` must have exactly
that span length. Canonical excerpt bytes are the corresponding stored packet
text joined with `\n`, without reading the repository again.
`excerpt_sha256` is lowercase SHA-256 of the UTF-8 encoding of those exact
canonical excerpt bytes.

Verification state is trusted metadata and is never accepted from the model:
`evidence_bound`, `corroborated`, `mechanically_verified`, `human_verified`,
or `disputed`. Model normalization produces only `evidence_bound`. A real
independent judge may produce `corroborated`; a named deterministic predicate
may produce `mechanically_verified`; an exact accepted disposition produces
`human_verified`; an exact rejected disposition produces `disputed`.

Only `mechanically_verified` and `human_verified` are failure-authoritative.
Configuration whose final resolved policy gives `error` to an
`evidence_bound` or `corroborated` semantic diagnostic is invalid and exits
`2`. Candidate states never cause exit `1`, even when another visible level in
`fail_on` would otherwise match.

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

| Code | evidence_bound | corroborated | mechanically_verified | human_verified | disputed |
|---|---|---|---|---|---|
| `SEMANTIC_CONFIRMED_MISMATCH` | warning | warning | warning | warning | info |
| `SEMANTIC_PROBABLE_MISMATCH` | info | info | warning | warning | info |
| `SEMANTIC_MISSING_TRACE` | warning | warning | warning | warning | info |
| `SEMANTIC_WEAK_BINDING` | warning | warning | warning | warning | info |
| `SEMANTIC_AMBIGUOUS` | info | info | info | info | info |

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
`human_verified`; `rejected` produces `disputed`.
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
not exact while its level is in `fail_on`.

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

`candidate_handling` is exact:

- `allow`: show and count undisposed candidates; create no debt warning and no
  exit effect
- `report`: additionally record each undisposed candidate in
  `candidate_debt` and emit a concise stderr warning; no exit effect
- `require_disposition`: record the same debt and exit `2` when any candidate
  remains undisposed

Cached classification stays policy-neutral. Changing policy or dispositions
reprojects the same cache objects with zero provider calls.

### 7. Completeness, Reports, Budgets, And Exit Codes [SEM-7]

Packet generation accepts an optional sidecar:

```bash
backstitch packets ... --output packets.jsonl --report packet-report.json
```

The resolved packet output and non-null report paths must be distinct. Equality
is invalid input and exits `2` before temporary creation or publication.

The packet report is a closed object:

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

Because eligible counts precede `--kind` filtering, analysis cannot derive an
excluded kind's eligible population from the filtered packet file. It validates
that each eligible count is a nonnegative integer at least its emitted count,
but treats eligible counts as generator-reported coverage context with no gate
authority. The exact digest, packet IDs and hashes, emitted counts, warning
count, and prompt bytes are independently recomputed from the packet file and
must match.

Analysis accepts:

```bash
backstitch analyze --packets packets.jsonl \
  --packet-report packet-report.json \
  --output analysis.jsonl --report analysis-report.json
```

The resolved analysis output and non-null report paths must be distinct.
Equality is invalid input and exits `2` before temporary creation, cache work,
adapter construction, provider work, or publication.

`--packet-report` is required exactly when any of these is true:
`require_complete`; `required_kinds` is nonempty; `minimum_packets > 0`;
`maximum_packets > 0`; `maximum_prompt_bytes > 0`; or `packet_warnings` is
`report` or `error`. Its digest, IDs, hashes, emitted counts, warning count, and
prompt bytes must match the packet file; eligible counts follow the narrower
validation above.

The optional analysis report is closed and has exactly `schema_version = 1`,
`artifact = "backstitch-analysis-report"`, `packet_jsonl_sha256`,
`result_jsonl_sha256`, `status` (`complete`, `incomplete`, or `failed`),
`analysis_exit_code`, `packet_count`, `result_count`, `packet_warning_count`,
`packet_warning_debt`, `candidate_debt`, `cache_hits`, `cache_misses`, `provider_calls`,
`prompt_byte_count`, `elapsed_milliseconds`, nullable
`estimated_cost_microusd`, nullable `cost_rate_source`,
`effective_policy_layers`, `semantic_diagnostics`, `unused_dispositions`, and
`problems`. `analysis_exit_code` is the pre-publication semantic/completeness
decision; an output publication failure can still make the command and returned
run exit `2`. Canonical result JSONL is policy-neutral and byte-stable; this
operational report is not.

Nested analysis-report records are also closed. A problem has exactly nullable
`packet_id`, `stage`, `code`, and `message`. Stage is one of `config`, `input`,
`cache`, `lock`, `provider`, `normalization`, `completeness`, `budget`,
`output`, or `internal`. Code is one of `invalid_config`, `invalid_input`,
`corrupt_cache`, `stale_cache`, `lock_timeout`, `provider_failure`,
`malformed_result`, `incomplete_result`, `budget_exceeded`, `output_failure`,
or `internal_failure`, paired with its corresponding stage. Packet-warning
debt entries have exactly `packet_id` and `warnings`, preserving packet order
and warning-string order; the aggregate list length across entries equals
`packet_warning_count`. Candidate-debt
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
`incomplete` when a completeness/budget problem exists, packet warnings are an
error, or required candidate disposition is absent; otherwise it is
`complete`. `analysis_exit_code` follows [SEM-7] precedence from that state and
diagnostics. A later publication failure appears in the returned run problems
and final exit; if the report itself could not be published, it cannot falsely
claim to contain that event.

A packet model/provider/normalization failure emits no canonical result row and
no BSA diagnostic. It appends one closed structured problem with `packet_id`,
`stage`, `code`, and `message`, continues with later packets subject to budgets,
makes the report status `failed`, and forces exit `2`. Such a problem never
satisfies `require_complete`. The returned JSONL may therefore contain valid
rows for successful packets only. The CLI publishes returned partial JSONL and
the failed report using its ordinary atomic output contract; an output failure
still takes precedence. There is no v2 `ambiguous` error-row escape hatch.

`packet_warnings` is exact: `allow` counts only; `report` also records coverage
debt and warns on stderr; `error` makes analysis incomplete and exits `2`.
Packet warnings never become target diagnostics or exit `1`.

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
another cache owner. `lock_stale_seconds` is used only by explicit lock
cleanup. `maximum_runtime_seconds` is checked before scheduling work and after
each provider return; it stops new calls and makes an overrun exit `2`, but the
first implementation does not claim it can cancel an arbitrary in-flight
`llm` request. The former `timeout_seconds` key is removed, not silently
reinterpreted. A hard per-call timeout requires a future adapter contract with
real cancellation. No timeout becomes a target finding or an automatic
cache-miss retry.

Exit precedence is:

| Condition | Exit |
|-----------|-----:|
| Invalid config/input, duplicate IDs, corrupt/stale cache, lock timeout, provider failure, malformed result, output failure, or internal failure | 2 |
| Missing required kind/count/report, count/prompt/call/runtime/cost budget exceeded, or `packet_warnings = "error"` with warnings | 2 |
| Any packet lacks one valid result when `require_complete = true` | 2 |
| `candidate_handling = "require_disposition"` and an undisposed candidate remains | 2 |
| Eval enforce mode has an undefined metric, unmet sample floor, or failed threshold | 2 |
| Required analysis completed and an exact human/mechanical semantic diagnostic has an effective level in `fail_on` | 1 |
| Otherwise | 0 |

Tool and completeness failures take precedence over target findings. Policy
cannot convert them to exit `0` or `1`.

### 8. Measured Semantic Evaluation [SEM-8]

The public entry point is:

```bash
backstitch eval --corpus tests/semantic_eval/v1/manifest.json \
  --output semantic-eval-report.json
```

`eval` accepts `--config` and `--no-config`; discovery anchors at the manifest
parent. It builds every case through production scan, resolution,
packetization, semantic analysis, evidence, cache, and policy. It never accepts
hand-built packets/results. It exits `2` for corpus, transform, provider,
cache, artifact, or output failure. In report mode, undefined metrics are
`null` and do not fail. In enforce mode, undefined or under-sampled metrics and
threshold failures exit `2`. `eval` never exits `1` because qualification is a
tool/corpus decision, not a target-repository finding.

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
| `trace_reference_removed` | positive | Remove one required code-side trace reference while retaining implementation; expect `SEMANTIC_MISSING_TRACE` |
| `equivalent_refactor` | negative | Apply a behaviorally equivalent expression change |
| `nonsemantic_comment_edit` | negative | Change only an explanatory comment |
| `prompt_injection_comment` | negative | Insert instruction-like text captured in the packet; it has no authority |
| `out_of_packet_decoy` | negative | Add mismatch-like text outside the packet projection |

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

The report top level is closed and contains exactly `schema_version = 1`,
`corpus`, `analysis`, ordered `trials`, `metrics`, `qualification`, and
`operational`. Corpus records only corpus ID/version and manifest hash.
Analysis records only model/revision, offline provider descriptor, controls,
prompts, and contract version. Each trial records only trial index/ID/epoch,
ordered case/variant outcomes, canonical and replay result digests, cache
counts, provider calls, estimated cost, and provider latency. Qualification
records only mode, sample-floor/threshold checks, promotion invariants, and
failure reasons. Operational records only current-run duration and totals; it
is not byte-stable.

The closed nested keys are:

- `corpus`: `corpus_id`, `corpus_version`, `manifest_sha256`
- `analysis`: `backend_id`, `plugin_id`, `model_id`, `model_revision`,
  `adapter_id`, `adapter_version`, `llm_distribution_version`,
  `plugin_distribution_name`, `plugin_distribution_version`, `request`,
  `prompts`, `analysis_contract_version`
- each trial: `trial_index`, `trial_id`, `effective_search_epoch`, `outcomes`,
  `canonical_result_sha256`, `replay_result_sha256`, `cache_hits`,
  `cache_misses`, `provider_calls`, `replay_provider_calls`,
  `estimated_cost_microusd`, `provider_latency`
- each outcome: `case_id`, `family`, `variant`, `label`,
  `expected_packet_id`, `captured`, nullable `expected_code`, `detected`,
  `hard_fail_predictions`, `valid_rows`, `complete`, `gold_evidence_atoms`,
  `matched_gold_atoms`
- `metrics`: `capture_rate`, `conditional_recall`, `end_to_end_recall`,
  `valid_row_rate`, `complete_result_rate`, `gold_evidence_overlap`,
  `hard_fail_precision`, `negative_control_false_positive_rate`,
  `ambiguous_rate`, `uncached_flip_rate`, `replay_stability`,
  `estimated_cost_microusd`, and `provider_latency`
- `qualification`: `mode`, `sample_floor_checks`, `threshold_checks`,
  `promotion_invariants`, and `failure_reasons`
- `operational`: `elapsed_milliseconds`, `provider_calls`, and
  `estimated_cost_microusd`

The analysis request subobject reuses the exact [SEM-3] request keys. Each
prompt descriptor has exactly `kind`, `id`, `version`, and `sha256`. Each hard
fail prediction has exactly `code`, `packet_id`, and `finding_hash`. Each gold
atom is a three-item JSON array `[role, path, line]`. Each sample-floor or
threshold check has exactly `name`, `actual`, `operator`, `required`, and
`passed`; nullable actual/required values represent undefined metrics. Each
promotion invariant has exactly `name` and `passed`. Failure reasons are
strings. Every proportion metric uses the closed metric shape below. Provider
latency has exactly `count`, `total_ms`, and `maximum_ms`; the last two are
nullable only under the unavailable-data rule below. These records may only
gain fields with a report schema-version change.

Each proportion metric records numerator, denominator, value, Wilson lower,
and Wilson upper. With denominator zero, value/bounds are `null`. Otherwise
value is numerator/denominator and Wilson uses
`statistics.NormalDist().inv_cdf(0.5 + confidence_level / 2)` with the standard
score formula.

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

Cost sums production estimates. Latency reports monotonic count/total/max.
Zero-call replay cost/latency is zero; unavailable data for a real call is
`null` and named by qualification.

Enforce mode fails on an undefined configured metric, unmet positive/negative
sample floor, replay provider call, or threshold failure. Promotion also
requires artifact validity and completeness 1.0, zero hard-fail negative
rows, every critical positive detected in every trial, reviewed recall/Wilson
thresholds, and byte-identical zero-call replay. Code and packaged defaults do
not invent promoting thresholds.

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
packet_warnings = "report"     # allow | report | error
candidate_handling = "report"  # allow | report | require_disposition
maximum_provider_calls = 1000
lock_wait_timeout_seconds = 300
lock_stale_seconds = 3600
maximum_runtime_seconds = 1800
maximum_estimated_cost_microusd = 0
input_cost_microusd_per_million_tokens = 0
output_cost_microusd_per_million_tokens = 0
input_token_overhead = 256
cost_rate_source = ""

[analyze.eval]
mode = "report"                # report | enforce
corpus_version = "1"
trials = 1
interval_method = "wilson"
confidence_level = 0.95
minimum_positive_trials = 0
minimum_negative_trials = 0
minimum_capture_rate = 0.0
minimum_conditional_recall = 0.0
minimum_end_to_end_recall = 0.0
minimum_recall_lower_bound = 0.0
minimum_precision = 0.0
maximum_false_positive_rate = 1.0
maximum_false_positive_upper_bound = 1.0
maximum_ambiguous_rate = 1.0
maximum_uncached_flip_rate = 1.0
require_all_critical = false
```

`analyze.model` maps to inference-contract `provider.model_id` after ordinary
CLI/config precedence. `backend_id` has packaged default `llm`; `plugin_id`,
`model_revision`, and `model` have no invented cached identity. `cache_mode =
"off"` retains the existing optional model resolution. `read-write` and
`require` require all five declared provider identity strings to be nonblank before
adapter construction. Packaged defaults use `cache_mode = "off"`,
`json_mode = "prefer"`, non-promoting zero eval sample floors, report mode,
and a zero cost ceiling. Backstitch's applied dogfood config sets every shown
key explicitly. Every `[analyze.eval]` key above is a strict known key; there
is no implicit additional eval setting.

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
| `packet_warnings` | `allow`, `report`, or `error` |
| `candidate_handling` | `allow`, `report`, or `require_disposition` |
| `maximum_provider_calls` | integer excluding booleans, at least 0; a literal ceiling, so zero permits no call |
| `lock_wait_timeout_seconds`, `lock_stale_seconds`, `maximum_runtime_seconds` | integer seconds excluding booleans, at least 1 |
| `maximum_estimated_cost_microusd` | integer excluding booleans, at least 0; zero disables the cost ceiling |
| input/output cost rates, `input_token_overhead` | integers excluding booleans, at least 0 |
| `cost_rate_source` | string; nonblank when the cost ceiling is positive |
| eval `mode` | `report` or `enforce` |
| eval `corpus_version` | nonblank string |
| eval `trials` | integer excluding booleans, at least 1 |
| eval `interval_method` | exactly `wilson` |
| eval `confidence_level` | finite number strictly between 0 and 1 |
| eval minimum sample floors | integers excluding booleans, at least 0 |
| all eval rate/threshold keys | finite numbers from 0 through 1 |
| eval `require_all_critical` | boolean |

Cross-field validation is exact: `prefer` requires cache off; cached modes
require nonblank backend, plugin, plugin distribution, model, and model
revision; require mode makes zero calls regardless of its shared refresh
ceiling; a nonzero
`maximum_packets` must be at least `minimum_packets`; a positive cost ceiling
requires nonblank source and explicit rate/overhead values; eval enforce mode
requires both sample floors to be positive, every minimum rate/precision/lower
bound to be greater than zero, every maximum rate/upper bound to be less than
one, and `require_all_critical = true`.
Semantic failure-authority rules are [SEM-5]/[SEM-6]. Duplicate disposition
identities, duplicate required kinds, noncanonical hashes, unknown keys, and
all invalid combinations exit `2` before cache or adapter work.

Packaged defaults are exact: `backend_id = "llm"`; blank `plugin_id`,
`plugin_distribution_name`, `model`, and `model_revision`; `concurrency = 1`;
`json_mode = "prefer"`; `temperature = 0.0`; `seed = 42`; `max_tokens = 512`;
`cache_path = ".backstitch/semantic-cache"`; `cache_mode = "off"`;
`search_epoch = "1"`; `require_complete = false`; `required_kinds = []`;
`minimum_packets = 0`; `maximum_packets = 1000`;
`maximum_prompt_bytes = 10000000`; `packet_warnings = "report"`;
`candidate_handling = "report"`; `maximum_provider_calls = 1000`;
`lock_wait_timeout_seconds = 300`; `lock_stale_seconds = 3600`;
`maximum_runtime_seconds = 1800`; `maximum_estimated_cost_microusd = 0`;
both cost rates are zero; `input_token_overhead = 256`; and
`cost_rate_source = ""`. Eval packaged defaults are the values in the TOML
block above. They are report-only and non-promoting.

A repository may set a positive cost ceiling only with reviewed provider rates
and a dated source. Until those values are reviewed, the dogfood configuration
must explicitly retain the zero disabled ceiling; zero cloud rates paired with
a positive ceiling are not a conservative budget.

The rollout rungs remain report-only baseline, measured policy, trusted
refresh, human review/commit, required main/release replay, then separately
threat-modeled pre-merge gating.

The report-only rung commits the corpus manifest/fixtures before provider
population. The trusted cold run records manifest hash, trial IDs/epochs,
schema versions, metrics, estimated cost, and latency. It may populate misses
and emit a review artifact, but it may not change TOML thresholds,
dispositions, committed cache objects, or CI policy. Human review selects
nonzero sample floors and thresholds in a later change.

Required replay runs the same eval command in `require` mode and reproduces
classification, evidence, qualification metrics, and canonical JSONL with zero
provider calls. A corpus, prompt, request, model, contract, or epoch change
exits `2` until trusted refresh artifacts are reviewed and committed.

The semantic replay lane is main/release only in v1 and never receives a
provider secret. The refresh lane is manual-only, checks out trusted main,
requires the provider credential, runs `read-write`, uploads a review artifact,
and never commits or pushes. Neither lane is activated by a repository Actions
variable. Pull-request-controlled code/config/hooks/install/output never run
with the secret.

All nonsecret controls live in `pyproject.toml`. The explicitly selected
`.backstitch-refresh.toml` is a closed override document: its only top-level
key is `extend = "pyproject.toml"`; its only table/key is
`[analyze] cache_mode = "read-write"`. Output/report paths remain CLI
arguments. Any other refresh key/table is exit `2`.

## Companion Spec Amendments

### [SC-5] CLI And Exit Contract

Add packet/report, analyze/report, `backstitch eval`, and
`backstitch cache cleanup-lock` commands above. `summarize-analysis` is
presentation-only: it validates every input row, exits `2` for any malformed
report/result, never applies semantic policy or dispositions, never asserts
verification state, and never exits `1`.

### [CFG-3] Discovery Anchors

`eval --config` and ordinary eval discovery anchor at the corpus manifest's
parent directory. `cache cleanup-lock` performs no discovery and requires
explicit cache path, analysis key, stale seconds, and reason. Packet and
analysis report output paths do not affect config discovery.

### [SC-6] Artifact Transition

New packet and analysis-result rows are version 2 and producers emit only v2.
Read-only compatibility accepts: current unversioned section/invariant packet
rows; legacy section packets without kind; current unversioned
section/invariant result rows; and legacy section results without kind. Legacy
packets may run only with cache mode off. Legacy results may only be rendered
by `summarize-analysis` and have no gate authority. Partial version markers,
mixed legacy/new fields, and unversioned cache objects are malformed. The
existing deterministic report transition is unchanged.

Accepted unversioned packets normalize in memory before analysis. A section
without kind gains `kind = "section"`; all accepted packets gain
`schema_version = 2` and a recomputed [SEM-3] `packet_hash`; input instructions
are discarded. An unversioned invariant declaration gains `start_line = line`,
`end_line = line + max(1, len(statement.splitlines())) - 1`, and
`excerpt = statement`, using only bytes already shown by
that packet. The validated packet wrapper records `cache_eligible = false` and
configuration other than `cache_mode = "off"` is exit `2`. No normalized legacy
row is written back as a v2 artifact or cache object.

The v2 packet union is the exact [SEM-3] projection plus `schema_version = 2`
and `packet_hash`; invariant rows also carry `content_hash`.
The v2 valid-result union is the exact closed row in [SEM-4]. Model/provider
failures are report problems, not result rows. Packet cache objects use the
same projection without instructions, while result cache objects use the exact
schemas in [SEM-4]. This intentional split prevents artifact and cache version
numbers from being confused.

### [SC-7] Semantic Ownership And Live Proxy

All gate authority, evidence validation, caching, semantic diagnostics,
reports, and exit selection are owned by one production interface:

```python
run_semantic_analysis(request: SemanticAnalysisRequest) -> SemanticAnalysisRun
```

`SemanticAnalysisRequest` is one frozen object with exactly `packets` (ordered,
validated semantic packet objects), exact lowercase `packet_jsonl_sha256`
computed from accepted input bytes before normalization, nullable validated
`packet_report`, fully resolved `settings`, fully resolved semantic `policy`, nullable
`adapter_factory`, `result_path`, and nullable `report_path`. A validated packet
object contains its normalized v2 row plus a `cache_eligible` boolean that is
false for every accepted unversioned input.
The factory is a lazy external boundary, not a constructed adapter; it must be
null in `require` mode and is never invoked for a cache hit. Settings include
the offline provider identity, request controls, cache/completeness/budget
controls, and dispositions. Policy includes effective levels, winning rule
identity, and `fail_on`.

Request validation rejects equal resolved result and report paths before cache
or adapter work.

`SemanticAnalysisRun` is one frozen object with exactly ordered valid
`results`, projected semantic `diagnostics`, ordered structured `problems`,
`result_jsonl` bytes, the closed `report`, canonical `report_json` bytes,
ordered `stderr_lines`, and `exit_code`. `result_jsonl` is empty when no valid
row exists; otherwise it ends in one newline. `report_json` always ends in one
newline. The interface owns packet iteration, lazy adapter construction,
single flight, canonical serialization, policy, per-file output publication,
and final exit precedence. It writes same-directory temporaries, fsyncs them,
then atomically replaces the result path followed by the report path. There is
no false claim of cross-file transactionality: a report is the last completion
marker, and a crash or second replace failure can leave a new result with an
old or absent report. Any publication failure appends an output problem when
possible and returns exit `2`; `analysis_exit_code` in an already-built report
remains the pre-publication decision. CLI code loads config/artifacts, invokes
the interface once, emits returned stderr lines, and returns its final exit
code. It does not write semantic artifacts or re-evaluate any row or exit
condition. `summarize-analysis` does not call it.

For each packet, malformed model output or a provider failure produces no v2
result row, appends the [SEM-7] problem, and analysis continues when budgets
permit. This replaces the legacy advisory `ambiguous`/`error` row behavior for
v2. New evidence uses [SEM-5] roles and spans. The local live proxy may
record/assert configured provider-neutral controls, but may not inject,
replace, retry, or repair them.

Replace every SC-7 live assertion phrased in terms of per-row `error` fields or
total error rows. An enabled cloud live test requires report status `complete`,
no problems, and one valid v2 row per input packet. An enabled local-endpoint
transport test proves the production request reached the endpoint and applies
the same complete/no-problem assertion; malformed output is an exit-2 test
failure, not a tolerated row. A test-owned proxy may observe and record exact
requests but may not inject request controls, replace response format, retry a
packet, or repair content. The optional lane may remain disabled by its legacy
pytest gate; [SEM-9]'s semantic CI replay cannot.

### [SC-10] Acceptance Probes

Replace probe 13's error-row requirement: a controlled malformed response for
one packet yields no canonical row for that packet, one
`normalization/malformed_result` problem, continued processing of later
packets, and exit `2`. The resulting valid v2 rows, failed analysis report, and
problem schema must all validate. Update prompt/hash probes to assert that v2
packets contain no instructions, code-owned prompt changes alter the prompt
descriptor and analysis key but not packet hash, and every model-visible
projection change alters packet hash.

### [SC-13] Validation

Unknown packet input extensions remain tolerated but never enter the semantic
projection. Nested projected packet records, v2 results, versioned cache
objects, eval manifests, and eval report qualification data are closed because
their bytes or fields affect identity and qualification. Packet and analysis
reports are also closed public contracts. Rejection occurs before
adapter construction, cache mutation, provider traffic, or output publication
where the required facts are available.

### [SC-15] Semantic Registry Transition

At corrective-spec promotion, allocate all five [SEM-6] canonical/short code
pairs as `reserved` registry entries with the five verification-state contexts
and packaged level table. Reserved entries are recognized for config
validation but cannot be emitted. Each code becomes `implemented` only in the
same slice as its production projection and firing tests. Deterministic issue
inventories and suppressions exclude the semantic family; semantic diagnostics
use the shared registry resolver without becoming deterministic `Issue` rows.

### [CFG-6], [CFG-8], And [CFG-9]

Add `backend_id`, `plugin_id`, `plugin_distribution_name`, `model_revision`,
`json_mode`, `temperature`, `seed`, `max_tokens`, `cache_path`, `cache_mode`, `search_epoch`,
`require_complete`, `required_kinds`, `minimum_packets`, `maximum_packets`,
`maximum_prompt_bytes`, `packet_warnings`, `candidate_handling`,
`maximum_provider_calls`, `lock_wait_timeout_seconds`, `lock_stale_seconds`,
`maximum_runtime_seconds`, `maximum_estimated_cost_microusd`,
`input_cost_microusd_per_million_tokens`,
`output_cost_microusd_per_million_tokens`, `input_token_overhead`, and
`cost_rate_source` under
`[analyze]`, plus exactly the `[analyze.eval]` keys and
`[[analyze.dispositions]]` fields enumerated in [SEM-6] and [SEM-9]. Remove the
old `timeout_seconds` key; it has no honest v1 cancellation semantics.

Validate exact types, nonblank identifiers/reasons/sources, hashes, closed
vocabularies, nonnegative bounds, positive timeouts, mode combinations,
duplicate dispositions, refresh allowlist, and the final resolved semantic
policy. Every key has a no-op-prevention test. Config layers list every parent
and child in merge order.

### [INV-5], [INV-7], And [INV-9]

Invariant packets add the declaration excerpt/span and universal packet hash
without changing invariant `content_hash`. V2 result evidence follows the
role/span matrix above. Add firing tests for declaration evidence, all
invariant classifications, forged roles/spans/excerpts, hash independence,
cache hit/replay, and legacy cache-off acceptance.

Replace INV-7's legacy per-packet containment wording with [SEM-7]'s
problem-only v2 contract. Replace INV-9 and SEM-10 evidence expectations with
the exact [SEM-5] role matrix: one-sided evidence is valid only for the
classifications whose required role set is one-sided. SEM-10 packet-hash tests
cover every projection field; code-owned instructions are model-visible but
are intentionally prompt identity rather than packet identity.

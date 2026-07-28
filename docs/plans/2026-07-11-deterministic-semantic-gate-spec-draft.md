# Deterministic-Enough Semantic Gate Spec Draft

This draft is the exact proposed contract for
`docs/specs/06-semantic-gates.md`. It is review material until the promotion
slice copies it into `docs/specs/`.

Status: Proposed

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

## 2. Mental Model And Layering [SEM-2]

The semantic path is:

```text
deterministic packet
  -> inference fingerprint
  -> trusted immutable cache lookup
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

## 3. Packet And Inference Fingerprints [SEM-3]

Every new section and invariant packet carries `packet_hash`, a 64-character
lowercase SHA-256 digest of the entire validated semantic packet payload.
The payload is the model-visible packet data other than prompt instructions;
instructions have their own prompt identity below. Canonicalization excludes
`instructions`, `packet_hash`, and derived cache metadata; it includes packet
identity, kind, shown spec or invariant text, locators, ordered snippets/tests,
deterministic issues, and packet warnings. Serialize with sorted keys, compact
separators, ASCII escapes, and UTF-8.

The exact model request is the prompt instruction bytes followed by canonical
JSON of that semantic payload. Derived `packet_hash`, invariant `content_hash`,
cache metadata, and provenance are not sent to the model. Trusted normalization
attaches them after inference. Thus every field in the model-visible semantic
payload affects `packet_hash`; excluded derived fields are not model-visible.

The existing invariant `content_hash` remains unchanged comparison metadata for
the bounded statement/target/binding-test projection. It is not a cache key.

Each prompt has a stable prompt ID, a human-reviewed integer version, and a
SHA-256 hash of the exact UTF-8 instruction bytes. Semantic prompt changes bump
the version; the byte hash catches any unbumped edit.

Each analysis request has an inference contract containing:

- requested model and nonblank repository-declared model revision/fingerprint
- backend/plugin identity, code-owned adapter ID/version, and resolved provider
  capabilities that affect the request path
- exact resolved request controls, including the actual JSON mode, temperature,
  seed, and output-token bound when set
- prompt ID, version, and byte hash
- packet hash
- `analysis_contract_version`, a code-owned integer covering result schema,
  normalization, evidence rules, and adapter behavior
- repository-configured `search_epoch`, used to request a new frozen stochastic
  event without overwriting the prior event

`analysis_key` is SHA-256 of canonical JSON for that inference contract.
Backend/plugin and observed provider model fingerprints are recorded as
provenance as well as identity. `read-write` cache population requires a
nonblank repository-declared revision and one fully resolved request path;
`json_mode = "prefer"` must resolve before key construction. If the provider
exposes no immutable model revision, the result must say so; the repository
fingerprint is then an auditable assertion, not proof of provider weights.
Cache replay is deterministic but does not prove identical unseen weights
across distinct misses.

Changing packet bytes, prompt bytes/version, model fingerprint, request
controls, analysis contract version, or search epoch creates a miss. Changing
policy, rendering, concurrency, output path, or suppression does not.

## 4. Immutable Semantic Cache [SEM-4]

The cache is an untrusted, content-addressed store with two immutable object
families:

- `packets/<packet_hash>.json`: the canonical validated packet object
- `results/<analysis_key>.json`: request fingerprint, canonical result,
  provenance, raw-response digest, and creation metadata

An index may accelerate lookup but is rebuildable and non-authoritative.

Cache modes are:

- `off`: do not read or write the cache; call the model for every packet
- `read-write`: reuse valid hits, call the model only for misses, and publish
  immutable objects for successful misses
- `require`: require valid hits for every packet and make no model adapter or
  provider call; a miss is an incomplete analysis and exits `2`

Before a provider call, a process acquires an exclusive single-flight lock for
the analysis key. A waiter never makes a second call: it waits within the
configured timeout, then validates and reuses the published object. An expired
or abandoned lock exits `2` and requires an explicit audited cleanup; it does
not trigger a second stochastic event. The lock owner writes a temporary file
and atomically publishes it without overwriting an existing object. Different
bytes already published for one key are cache corruption and exit `2`.

Canonical packet and result objects contain only inference identity, normalized
result data, frozen provider response/provenance, and their digests. Run-local
timestamps, wait duration, cache counters, and process identity are operational
records outside these objects. The canonical result JSONL rendered from a
fixed packet order and fixed cache objects must be byte-identical on replay.
The operational run report is deterministic in meaning but is not promised to
be byte-identical because it includes duration and current hit/miss counters.

Every hit recomputes its key and revalidates packet schema/hash, result schema,
packet identity/kind/hash, prompt/model/request provenance, and evidence bounds
against the cached packet. A matching filename is never sufficient evidence of
trust. Cache corruption, stale provenance, or a result with invalid evidence
exits `2`; it never silently becomes a miss under `require` mode.

Backstitch's own authoritative cache is committed to the repository. GitHub
Actions caches and artifacts may accelerate or transport refreshes, but they are
not the source of truth because they are evictable and weakly auditable.

## 5. Evidence And Verification State [SEM-5]

Model evidence is untrusted input. Each cited path and exact line span must be
inside content shown in the packet. Canonical evidence records the matched
packet role and exact excerpt or excerpt digest so replay can prove what bytes
were cited. Model-supplied quotes, roles, packet identity, hashes, and
provenance are ignored and replaced from trusted packet/request data.

Evidence roles include at least:

- `requirement`: section text or invariant declaration/statement
- `implementation`: owner or invariant target code
- `test`: shown binding-test code

Any finding considered for policy must be evidence-bound and meet
classification-specific role requirements. A confirmed mismatch requires both
requirement and implementation evidence. A weak binding requires implementation
and shown test evidence. Absence claims such as `missing_trace` cannot become
mechanically verified merely by citing one present line.

Verification state is trusted metadata, never set by the model:

- `evidence_bound`: schema, identity, locality, exact excerpt, and required
  evidence roles validated
- `corroborated`: an independent configured judge agreed on the structured
  claim and evidence; this is stronger evidence, not proof
- `mechanically_verified`: a named deterministic predicate verified the claim
- `human_verified`: a repository-owned disposition accepted the finding
- `disputed`: a repository-owned disposition rejected or contested the claim

The first implementation may emit only `evidence_bound`; other states require
their own producer and firing tests. The model classification
`confirmed_mismatch` does not imply `human_verified` or
`mechanically_verified`.

`evidence_bound` and `corroborated` findings are candidates. They may require a
repository disposition, but they cannot be effective `error` findings in the
packaged policy or Backstitch's initial applied policy. Only
`mechanically_verified` and `human_verified` findings may be promoted to
`error`. A human disposition that accepts a finding produces `human_verified`;
a rejection produces `disputed`. This is the boundary that makes the model a
search heuristic rather than the final authority.

## 6. Semantic Diagnostics And Policy [SEM-6]

Every non-`ok` canonical result projects to one stable implemented diagnostic:

- `SEMANTIC_CONFIRMED_MISMATCH` (`BSA001`)
- `SEMANTIC_PROBABLE_MISMATCH` (`BSA002`)
- `SEMANTIC_MISSING_TRACE` (`BSA003`)
- `SEMANTIC_WEAK_BINDING` (`BSA004`)
- `SEMANTIC_AMBIGUOUS` (`BSA005`)

Their diagnostic contexts are the trusted verification states from [SEM-5],
not model-generated labels. Model/provider/cache/input failures are tool
failures and do not project to target diagnostics.

The exact packaged levels are:

| Code | evidence_bound | corroborated | mechanically_verified | human_verified | disputed |
|---|---|---|---|---|---|
| `SEMANTIC_CONFIRMED_MISMATCH` | warning | warning | warning | warning | info |
| `SEMANTIC_PROBABLE_MISMATCH` | info | info | warning | warning | info |
| `SEMANTIC_MISSING_TRACE` | warning | warning | warning | warning | info |
| `SEMANTIC_WEAK_BINDING` | warning | warning | warning | warning | info |
| `SEMANTIC_AMBIGUOUS` | info | info | info | info | info |

Selectors use the existing `CODE:context` syntax and existing later-rule-wins
precedence. The Backstitch pre-promotion TOML has a later `select = ["BSA*"]`,
`level = "info"` rule after its broad `*` rule. After measured promotion it
adds still-later exact error rules only for reviewed code/context pairs such as
`SEMANTIC_CONFIRMED_MISMATCH:human_verified` and
`SEMANTIC_CONFIRMED_MISMATCH:mechanically_verified`. It never promotes
`evidence_bound` or `corroborated` to error.

Semantic diagnostic records preserve:

- canonical and short diagnostic code
- raw classification and packet kind/identity/hash
- verification state
- trusted evidence
- packaged `default_severity`
- effective repository `severity`
- summary and rationale as presentation, never identity
- analysis key and policy-layer provenance

The packaged default policy is conservative: semantic findings are visible but
do not fail by default. Backstitch's repository-applied policy in
`pyproject.toml` may promote selected evidence-bound semantic codes to `error`
and uses the ordinary `diagnostics.fail_on` mechanism. The repo's earlier
`select = ["*"]` rule must be followed by explicit semantic-family rules so a
future semantic code cannot become a dogfood error accidentally.

Cached classifications remain policy-neutral. `backstitch config show` renders
the packaged default and effective semantic levels and the contributing config
layers. `--no-config` and Backstitch's applied config must be observably
different on the same cached result.

A disputed finding requires an exact repository-owned disposition keyed by
diagnostic code, packet identity/hash, and finding fingerprint with a nonblank
reason. Broad file- or family-wide semantic suppression is not accepted in the
first implementation. Dispositions remain auditable in the equivalent of
`--show-suppressions`.

Repository dispositions use this TOML shape:

```toml
[[analyze.dispositions]]
code = "SEMANTIC_CONFIRMED_MISMATCH"
packet_id = "section:SC-7"
packet_hash = "<64 lowercase hex>"
finding_hash = "<64 lowercase hex>"
status = "accepted"             # accepted | rejected
reason = "Reviewed against SC-7 and the cited implementation."
```

The finding hash covers code, classification, canonical claim, and trusted
evidence. A disposition that does not match all fields is unused and reported.

## 7. Completeness And Exit Codes [SEM-7]

Semantic target findings and search completeness are separate.

Configurable completeness controls include:

- required packet kinds
- minimum and maximum packet count
- maximum aggregate prompt bytes
- whether packet warnings are allowed, rejected, or reported as coverage debt
- whether every packet requires one valid result
- cache mode and miss behavior

The analysis report records eligible packet population, emitted packet
population, packet warnings/omissions, cache hits/misses, provider calls,
valid/error result counts, prompt bytes, duration, and effective policy layers.
`--kind all` means all generated edge-bearing section packets and bound
invariant packets. It does not mean all repository code; the report must not
claim otherwise.

Exit precedence and behavior are exact:

| Condition | Exit |
|---|---:|
| Invalid config/input, duplicate IDs, corrupt/stale cache, lock timeout, provider failure, malformed result, output failure, or internal failure | 2 |
| Required kind/count missing, packet count or prompt-byte budget exceeded, provider-call/runtime/cost budget exceeded, or `packet_warnings = "error"` with warnings | 2 |
| Any packet lacks one valid result when `require_complete = true` | 2 |
| Candidate lacks a matching disposition when `candidate_handling = "require_disposition"` | 2 |
| Eval mode is `enforce` and a metric is undefined, its sample floor is unmet, or a configured threshold fails | 2 |
| Required analysis completed and at least one effective semantic level is in `fail_on` | 1 |
| Otherwise | 0 |

Provider, cache-integrity, and malformed-result failures always exit `2`.
`require_complete = false` permits an absent result only when its cause is an
explicit allowed cache miss or candidate policy; it never converts a provider
or integrity failure to green. Policy cannot turn a tool/completeness failure
into exit `0` or `1`.

## 8. Measured Semantic Evaluation [SEM-8]

Backstitch maintains a repository-owned evaluation corpus of paired clean and
mutated cases generated through production parsing, resolution, packetization,
analysis, evidence validation, cache, and policy paths. Mutation metadata is
not shown to the model.

Each mutation has a stable ID/family, guarded source transformation, expected
packet identity, expected semantic diagnostic, exact changed/evidence spans,
criticality, clean twin, and expected packetization status.

The lane separates:

- packet capture rate
- judge recall conditional on capture
- end-to-end mutation recall
- valid-row and complete-result rate
- evidence-locality and gold-evidence overlap
- hard-fail precision and false-positive rate on labelled negative controls
- abstention/ambiguous rate
- uncached classification/evidence flip rate
- cached replay byte stability and provider-call count
- cache-miss cost and latency

Recall alone cannot qualify a hard gate because cache freezes false positives as
readily as true positives. Promotion requires 100% artifact validity and
required-result completeness, zero hard-fail false positives in the labelled
negative corpus, no critical-family miss, a reviewed recall threshold with a
reported confidence interval, and byte-identical zero-call cache replay.

Thresholds, model, request controls, trials, corpus version, interval method,
confidence level, and positive/negative sample floors are non-secret TOML
configuration. Enforce mode uses Wilson score intervals. Undefined metrics,
zero denominators, and unmet sample floors exit `2`. Initial promoting
thresholds and nonzero sample floors are recorded only after the first cold
baseline; they are not guessed in code.

## 9. Backstitch Dogfood And CI Trust Boundary [SEM-9]

Backstitch dogfoods the gate in stages:

1. report-only cache/eval baseline
2. repository-applied policy reviewed against measured recall and precision
3. trusted refresh that calls the provider only on immutable misses and emits a
   reviewable cache/disposition patch
4. human review and commit of cache objects and required dispositions
5. cache-required main/release replay gate over the committed cache
6. pre-merge required gate only after a separate two-stage threat-model review

The package default remains advisory throughout.

Backstitch's applied non-secret controls live in `pyproject.toml` or an explicit
repository TOML that extends it: model identity, inference controls, cache
path/mode, search epoch, completeness/budget controls, semantic policy, and eval
thresholds. CI supplies only event/ref context, runner paths when unavoidable,
and provider secrets. No repository Actions variable may silently activate or
deactivate the effective semantic policy.

The supported non-secret configuration is explicit:

```toml
[analyze]
model = "provider-model-id"
model_revision = "repository-declared-revision"
concurrency = 1
json_mode = "require"          # require | prefer | off
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
timeout_seconds = 1800
maximum_estimated_cost_microusd = 10000000

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

Packaged values are conservative. Backstitch sets every listed key explicitly
in its applied TOML. Until a cold baseline is reviewed, the applied eval mode is
`report` and its numeric thresholds are non-promoting sentinels shown above.
Promotion replaces those values with measured thresholds and changes mode to
`enforce`; code never supplies an invented passing threshold. CLI flags may
override controls for interactive use, but the dogfood CI command passes only
artifact paths and an explicit config path. Workflow YAML must not contain a
second copy of these values.

The trusted refresh file is `.backstitch-refresh.toml`. It has
`extend = "pyproject.toml"`; extending a `pyproject.toml` selects its
`[tool.backstitch]` table before merging. Its only permitted overrides are
`analyze.cache_mode = "read-write"` and operational output paths. All other
dogfood controls come from `pyproject.toml`. The cache and refresh files are
excluded from packet roots so cache publication cannot change its own packet
hashes.

A provider-secret workflow never executes pull-request-controlled code,
configuration, hooks, package installation, or output paths. A future PR gate
must split unprivileged packet production from privileged analysis using a
trusted released/base Backstitch binary, validate the packet artifact as
hostile input, and bound path roots, count, bytes, runtime, and cost before
provider traffic. `pull_request_target` may not simply check out and execute PR
code.

The initial Backstitch replay gate is a main/release gate, not yet a branch
protection gate. A changed packet intentionally makes replay exit `2` until a
trusted refresh artifact is reviewed and committed. Refresh never pushes or
commits by itself. The initial Backstitch gate reports packet warnings as
coverage debt rather than
rejecting them because the current corpus has warnings on most packets. Gate
status must show the warning count and cannot call the result full-repository
coverage. Packet-quality improvements are measured separately.

## 10. Verification Expectations [SEM-10]

Executable gates cover:

- mutation matrices proving every model-visible packet field changes
  `packet_hash` and policy/render/concurrency changes do not change
  `analysis_key`
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
- actionable classifications reject empty or one-sided evidence
- canonical evidence excerpts/ranges match packet bytes and roles
- `config show`, `--no-config`, extend layering, unknown keys, and every
  behavior-affecting config key have firing/no-op-prevention tests
- mutation and negative-control metrics are reproducible from committed cache
- a second identical dogfood run is byte-identical with zero provider calls
- CI missing-secret and cache-miss behavior cannot silently pass a required
  refresh/gate lane
- the ordinary acceptance probes and self-corpus gate remain green

## Related Plans

- `docs/plans/2026-07-11-deterministic-semantic-gate-plan.md`

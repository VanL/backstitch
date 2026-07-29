# Evidence-Stable Semantic Result Reuse Plan

Status: implemented and verified; final independent review PASS. The
owner-authorized landing commit includes this plan and its implementation.

Class: 5. This changes public configuration, semantic cache selection,
immutable cache storage, analysis-report schema, provider/model precedence,
and qualification behavior. It introduces a new persistent cache object and
therefore requires the hardening, rollout, compatibility, and independent
review gates.

## Goal

Keep one complete evidence-bound inference result in force while its complete
model-visible packet and review contract are unchanged, even when configuration,
`LLM_MODEL`, or `--model` selects a different model for new work. New or changed
packets use the currently selected model. Carried results retain their original
classification, rationale, selected evidence, inference key, and provider
provenance. Operators can opt out with `analyze.result_reuse =
"exact-inference"` or establish a new evidence-stable decision by changing
`analyze.search_epoch`.

The same change makes cached model precedence honest: a cached winning model
selects one complete trusted model descriptor instead of inheriting another
model's revision, plugin identity, or prices.

## Requested Outcomes

- [x] Add a provider-independent `review_key` derived from the packet, prompt,
  request, analysis-contract version, and search epoch.
- [x] Add one immutable first-writer baseline object per review key.
- [x] Make `analyze.result_reuse = "evidence-stable"` the packaged default.
- [x] Preserve the existing exact inference behavior through
  `result_reuse = "exact-inference"`.
- [x] Keep result objects and their provenance atomic. Never relabel a carried
  result as output from the selected model.
- [x] Permit results from different models to coexist in one current report,
  with exact and carried counts plus producer identities.
- [x] Make `LLM_MODEL` and `--model` obey CLI/environment/config precedence in
  cached modes by selecting a complete trusted model descriptor.
- [x] Keep one cache root across model changes. Do not delete it or reset
  caching to `off`.
- [x] Change Backstitch's dogfood update mode from `require` to `read-write` so
  new or changed evidence can be evaluated by the selected model while
  unchanged evidence carries forward.
- [x] Preserve fail-closed qualification: qualification never transfers from
  one analyzer identity to another.
- [x] Preserve exact legacy cache hits and provide bounded warmup without
  scanning the full result tree.

## Source Documents

- `docs/specs/02-backstitch-core.md` [SC-5]
- `docs/specs/03-backstitch-configuration.md` [CFG-5], [CFG-6], [CFG-8],
  [CFG-9]
- `docs/specs/06-semantic-gates.md` [SEM-3], [SEM-4], [SEM-5], [SEM-7],
  [SEM-9], [SEM-10]
- `docs/specs/07-verification-and-evidence-cases.md` [EVC-5], [EVC-6],
  [EVC-9.1], [EVC-10.1], [EVC-12]
- `docs/plans/2026-07-28-configured-default-command-plan.md`
- `docs/plans/2026-07-27-semantic-analysis-lifecycle-plan.md`
- `docs/plans/2026-07-27-canonical-config-resolution-plan.md`
- `docs/agent-context/runbooks/writing-plans.md`
- `docs/agent-context/runbooks/hardening-plans.md`
- `docs/agent-context/runbooks/adversarial-acceptance-probes.md`

## Spec Baseline

- `b33804a03f25168ea02bb4c9dc732c8cabaa2c75`:
  `docs/specs/02-backstitch-core.md`,
  `docs/specs/03-backstitch-configuration.md`,
  `docs/specs/06-semantic-gates.md`, and
  `docs/specs/07-verification-and-evidence-cases.md` at plan authoring time.
- Plan type: implementation with spec revision.
- Promotion baseline: the SHA above plus the current worktree diff in those
  three spec files and this plan. Implementation compliance is against that
  promoted worktree until the spec slice receives a commit SHA.

## Proposed Spec Delta

Promotion strategy: **A, direct in-file promotion to active sections before
implementation**. The delta is large and already applied in the same worktree;
the exact review target is:

```bash
git diff b33804a03f25168ea02bb4c9dc732c8cabaa2c75 -- \
  docs/specs/03-backstitch-configuration.md \
  docs/specs/02-backstitch-core.md \
  docs/specs/06-semantic-gates.md \
  docs/specs/07-verification-and-evidence-cases.md
```

| Spec file | Active sections | Promoted contract |
|-----------|-----------------|-------------------|
| `docs/specs/02-backstitch-core.md` | [SC-5] | explicit review-key abandoned-lock cleanup target |
| `docs/specs/03-backstitch-configuration.md` | [CFG-5], [CFG-6], [CFG-9] | `result_reuse`; exact model-descriptor catalog; CLI/environment model precedence without stale identity/cost fields |
| `docs/specs/06-semantic-gates.md` | [SEM-3], [SEM-4], [SEM-9], [SEM-10] | review identity; immutable baseline object; evidence-stable/exact lookup; schema-5 report and firing gates |
| `docs/specs/07-verification-and-evidence-cases.md` | [EVC-6], [EVC-12] | carried-result qualification isolation; model-catalog acceptance matrix |

The active spec text, not an appendix copy in this plan, is the sole governing
contract after promotion. If independent review changes any identity preimage,
object shape, failure priority, or qualification rule, amend the active spec
and record the disposition below before implementation.

## Current Structure And Key Files

Read these before implementation:

- `backstitch/semantic_identity.py`
  - `build_inference_identity()` hashes the complete packet, prompt, provider,
    request, contract version, and search epoch into `analysis_key`.
  - `InferenceIdentity` owns the canonical inference contract and prompt bytes.
  - Add review identity here. Do not derive it independently in cache/report
    callers.
- `backstitch/semantic_cache.py`
  - Analyzer packet objects live at `packets/<packet_hash>.json`.
  - Analyzer result objects live at `results/<analysis_key>.json`.
  - Hits are validated against the full current inference identity.
  - Per-analysis locks and guards serialize result production. Evidence-stable
    read-write adds an outer review-key lock whose only valid nested order is
    review key, then analysis key.
- `backstitch/semantic_analysis.py`
  - Resolves one selected analyze provider before cache inspection.
  - Performs read-only miss/cost/provider-call preflight before traffic.
  - Builds canonical result JSONL and the operational report.
  - Qualification is currently checked against one current composed
    analyzer/verifier identity.
- `backstitch/settings.py`
  - `_ANALYZE_KEYS`, `AnalyzeSettings`, `_parse_analyze_settings()`, generic
    option validation, environment overlay, dedicated CLI overrides, JSON
    projection, and model/revision cross-field validation own the public
    setting.
  - Model selection currently rejects a different cached environment/CLI
    model because only one flat descriptor exists.
- `backstitch/defaults.toml`
  - Add the packaged `result_reuse = "evidence-stable"` value.
  - Do not add an inactive model catalog to packaged defaults.
- `backstitch/semantic_reports.py`
  - Owns closed analysis-report validation. Current producers emit schema 4;
    this plan promotes schema 5 while retaining schema 3 and 4 readers.
- `backstitch/semantic_eval.py` and `backstitch/semantic_eval_reports.py`
  - Qualification evaluation uses fresh operation-scoped caches and exact
    inference replay. It must explicitly set exact-inference reuse so
    evidence-stable baselines cannot reduce trials or hide flips.
- `pyproject.toml`
  - Backstitch currently pins one model descriptor and `cache_mode = "require"`.
  - Add trusted catalog entries needed by supported `LLM_MODEL` values and
    switch ordinary dogfood analysis to `read-write`.
- `tests/test_semantic_cache.py`, `tests/test_semantic_analysis.py`,
  `tests/test_semantic_settings.py`, `tests/test_semantic_reports.py`,
  `tests/test_semantic_eval.py`, and `tests/acceptance/`
  - These must exercise real filesystem cache objects. Do not mock the cache,
    identity builder, settings resolver, report validator, or qualification
    boundary.

Comprehension gates:

1. Why does equal `packet_hash` alone fail to protect prompt, request, result
   normalization, and explicit resampling changes?
2. Why must the complete result and original provider provenance carry
   together rather than copying the result under the selected provider's
   `analysis_key`?
3. Why can a cache directory containing several compatible results not choose
   one by filesystem order, mtime, or lexicographic hash?
4. Why must evaluation trials force exact-inference behavior even though
   ordinary analysis defaults to evidence-stable reuse?
5. Why can a current-model qualification artifact not authorize a carried
   independently-verified finding produced by a different analyzer identity?

## Contract Decisions

### Review identity

The exact canonical review contract is:

```json
{
  "analysis_contract_version": 1,
  "packet_hash": "<sha256>",
  "prompt": {
    "id": "<code-owned id>",
    "version": 1,
    "sha256": "<sha256>"
  },
  "request": {
    "json_mode": "require|off",
    "temperature": 0.0,
    "seed": 42,
    "max_tokens": 512
  },
  "search_epoch": "1"
}
```

`review_key` is SHA-256 of the same canonical JSON function used for
`analysis_key`. Provider identity is the only inference-contract member
excluded. The UTF-8 bytes are the existing canonical JSON serialization of
the object shown above: sorted keys, ASCII output, separators `,` and `:`,
and no trailing newline. Changing any shown field invalidates the baseline.

### Baseline object

The exact object is:

```json
{
  "schema_version": 1,
  "object_type": "semantic-result-baseline",
  "review_contract": {},
  "review_key": "<sha256>",
  "analysis_key": "<sha256>"
}
```

It lives at `baselines/<review_key>.json`. Its target remains the ordinary
`results/<analysis_key>.json` object. Publish the result first, then publish
the baseline atomically with no replacement. A concurrent loser validates and
uses the winner. A missing or invalid target is corruption and exits `2`;
never choose another cached result as a fallback.

### Lookup order

For `evidence-stable`:

1. Compute the current packet's review identity.
2. If a baseline exists, validate the baseline, target result, original
   inference contract, packet, result evidence, and provenance. Use it.
3. In `require`, take a lock-free linearizable read: read the baseline; when
   absent, compute and validate the selected provider's exact result or exact
   miss; then read the baseline again. A valid second-read baseline wins,
   including qualification validation for its producer. If the second read is
   still absent, use the valid exact result or exit `2` for the exact miss.
   The absent second read is the operation's linearization point. `require`
   neither joins a baseline election nor mutates lock or baseline state.
4. In `read-write`, collect every packet with no baseline, sort its unique
   review keys lexically, acquire those per-review-key single-flight locks in
   that order, and recheck all baselines while owning the complete set. A
   waiter uses each valid winner.
5. Compute the selected provider's exact analysis key for every still-unowned
   baseline. Validate existing exact results, then perform run-wide
   qualification, completeness, call, cost, and runtime preflight over all
   winners and genuine misses before any provider work.
6. For each genuine miss, acquire the nested per-analysis-key single-flight
   lock and call the selected provider only if the exact result still misses.
   Publish any new result first, then its baseline. Release a review lock only
   after its baseline is valid or the run has failed. Only review-lock owners
   may make first baseline selections, so concurrent different-model
   read-write invocations have at most one active provider call for each review
   key and converge on the scheduling-dependent winner. Failed or explicitly
   cleaned owners may be retried later; failed calls never become baselines.

For `exact-inference`, ignore baseline objects and preserve the existing exact
analysis-key flow. Do not create or repoint a baseline. An operator who wants
a new result to become the next evidence-stable baseline changes
`search_epoch`, which creates a new review key.

### Model descriptor selection

The existing flat `[analyze]` identity and cost fields remain the descriptor
for its file-configured `model`. A trusted file may add:

```toml
[analyze.models."pkg:service/openai.com/gpt-5.4-mini"]
adapter_model_id = "gpt-5.4-mini"
backend_id = "llm"
plugin_id = "openai"
plugin_distribution_name = "llm"
model_revision = "gpt-5.4-mini-2026-03-17"
input_cost_microusd_per_million_tokens = 0
output_cost_microusd_per_million_tokens = 0
input_token_overhead = 256
cost_rate_source = "authoritative provider source, reviewed YYYY-MM-DD"
```

The quoted child key is the canonical Model Monster `pkg:service` PURL model
selector. The child `adapter_model_id` is the raw provider model name; the PURL
remains the inference identity. Ordinary precedence may select a descriptor by
its canonical PURL or unique adapter alias; the resolver restores
`analyze.model` to the canonical identity and uses either the flat descriptor
or the matching
catalog child. The selected descriptor atomically replaces adapter model,
backend, plugin, distribution, revision, and cost inputs. When file configuration
declares a nonblank flat model, an unknown different model or partial
descriptor is exit `2` before cache/provider work in every cache mode. Only
the legacy case with no file-declared model may use an uncached runtime model
with packaged blank optional identity/cost fields.

`extend` merges catalogs by exact selector. A later descriptor replaces the
complete earlier descriptor and cannot inherit omitted fields.

The flat descriptor is also one atomic file-layer group: `model`,
`backend_id`, `plugin_id`, `plugin_distribution_name`, `model_revision`,
both cost rates, `input_token_overhead`, and `cost_rate_source`. Any
non-packaged file layer that supplies one group member supplies the complete
group; a child cannot replace only `model`, revision, or rates and inherit the
rest. The group then replaces the inherited flat descriptor as one unit.
All non-model descriptor leaves are reserved from generic `--option`.
Dedicated `--model`, generic `--option analyze.model`, and `LLM_MODEL` only
select the already trusted flat or catalog descriptor by canonical identity or
unique adapter alias; they never construct one. Duplicate adapter aliases are
invalid.

The implementation must verify model revision and current price data against
an authoritative provider source at implementation time. Do not copy rates
from another model or infer prices from names. A positive cost ceiling cannot
run new misses without explicit rates and source.

### Reporting

Current analysis-report schema becomes 5 and adds:

- `result_reuse`
- `selected_inference`
- `exact_cache_hits`
- `carried_results`
- `result_sources`
- `result_providers`

`cache_hits = exact_cache_hits + carried_results`.
`selected_inference` contains the exact selected provider, request,
analysis-contract version, search epoch, and ordered kind-tagged prompt
descriptors needed to reconstruct the selected analysis key for every packet.
`result_sources` has one packet-order row per canonical result with exact
`packet_id`, `packet_hash`, `analysis_key`, `review_key`,
`result_object_sha256`, `inference_contract`, `provenance`, and `selection`,
where selection is `live`, `exact-cache`, or `carried`. Report construction
passes the ordered selected result envelopes to the validator, including the
same closed in-memory envelope for cache-off live results. It separately
passes an ordered, non-report operational selection event for each result with
exact `packet_id`, `packet_hash`, `result_object_sha256`, and runtime-observed
`selection`. The event is created at the branch that observes a new result,
an existing selected-key result, or a foreign-key baseline, not reconstructed
from report fields. The validator hashes each envelope, hashes
each inference contract, derives its provider and review contract, joins it to
the canonical result row and selection event, recomputes the selected analysis
key from `selected_inference`, and rejects any false producer, carry, live, or
exact-hit classification. Aggregate hit, call, carry, and provider counts
derive from these authoritative envelopes, selection events, and the existing
closed operational facts rather than trusting independent totals.
`result_providers` is sorted by canonical JSON of `provider` plus
`observed_model` and contains exact `provider`, `observed_model`,
`result_count`, and `carried_result_count` fields. `observed_model` carries
nullable model class, provider model ID, and provider model revision from the
immutable result provenance. Counts reconcile to top-level results and carried
totals. Canonical result JSONL remains unchanged and each row retains its
original `analysis_key`; the report ledger supplies the independently
hashable producer preimage and provenance.

### Qualification

Carried results may remain advisory under their original analyzer identity.
They may undergo current independent verification because verifier events
already bind the analyzer claim and `analysis_key`.

An exact `CODE:independently_verified` failure-authority selector may act only
when every analyzer result selected for the run is covered by the configured
passing qualification composition. If any result is carried from a different
analyzer identity, exit `2` with
`qualification/required_qualification_unavailable` before provider work or
report publication. Do not silently downgrade, relabel, or partially gate.

V1 supports one configured qualification artifact. A catalog of qualification
artifacts for mixed analyzer identities is out of scope.

## Invariants And Constraints

1. **Evidence means the full packet.** Cited result evidence alone never
   establishes currentness.
2. **Results are atomic.** Classification, confidence, rationale, summary,
   selected evidence, analysis key, inference contract, and provenance never
   split or get relabeled.
3. **Baseline selection is race-convergent.** First valid writer wins and all
   read-write participants use that winner. Scheduling may choose either
   concurrent model; directory order, mtimes, cache restore order, and hash
   ordering never choose or replace the result afterward. Read-only `require`
   observes one validated snapshot and does not participate in election.
4. **No source authority.** Baselines remain disposable cache acceleration,
   not reviewed source, disposition, or verification authority.
5. **No unbounded migration.** Runtime lookup never scans all result objects.
6. **Exact mode survives.** Evaluation, qualification replay, and explicit
   exact-inference analysis preserve provider-sensitive keys and calls.
7. **Provider quarantine survives.** Baseline hits in `require` construct no
   adapter, resolve no credential, and make no provider call.
8. **Cost truth survives.** Preflight counts only planned new calls and uses
   only the selected model descriptor's rates.
9. **Qualification fails closed.** Producer qualification never transfers.
10. **Legacy compatibility survives.** Existing exact result objects remain
    readable; new binaries do not rewrite them.
11. **No second settings path.** Model catalogs resolve inside the canonical
    settings resolver after ordinary model precedence.
12. **No verifier-cache redesign.** Verify keys continue to bind the analyzer
    result/claim and verifier provider under [EVC-3.1].
13. **No report-as-input shortcut.** Prior output/report files never satisfy a
    baseline.
14. **No hidden refresh.** Changing models alone does not refresh an
    evidence-stable baseline. `search_epoch` is the explicit refresh owner.
15. **No drive-by cache cleanup.** Fine-grained pruning and whole-root
    concurrent deletion remain out of scope.

Stop and revise the plan if implementation needs a mutable baseline pointer,
an unbounded cache scan, a second resolver, silent qualification downgrade,
or result copying under a false producer identity.

## Hidden Couplings And Failure Priorities

- Baseline lookup must happen before provider-call and cost preflight so carried
  work is counted as zero calls.
- Baseline selection may reveal producing identities different from current
  settings. Report aggregation and qualification validation therefore consume
  selected cache objects, not only `ResolvedSemanticSettings`.
- Evidence-stable read-write adds an outer per-`review_key` single-flight
  protocol. Its lock/guard/audit objects mirror the existing analysis-key
  state machine. A run acquires all needed review locks in lexical review-key
  order before qualification and provider preflight. Lock order is always the
  sorted review set, then an analysis key; no path acquires a review lock while
  owning an analysis lock. An outer review lock may span exact-result lookup,
  run-wide preflight, the nested analysis lock, one provider call, result
  publication, and baseline publication. Short guard locks never span
  provider work or sleeps. `lock_wait_timeout_seconds` bounds each wait and
  `maximum_runtime_seconds` bounds the whole command.
- Review waiters poll the baseline path. Result publication and analysis-lock
  cleanup complete first; baseline publication and review-lock cleanup then
  share one review-guard critical section. A caught failure releases every
  unchanged token-owned review lock acquired by the run. Process death leaves
  abandoned locks for the explicit `--review-key` cleanup path.
- An exact result may exist without a baseline after a crash or legacy run.
  This is valid. Read-write may backfill; require remains read-only.
- A baseline may not exist in a partially restored cache. Absence is a normal
  miss. Presence with an absent target is corruption because choosing another
  result would change the durable decision silently.
- Require-mode lookup is a two-read snapshot around exact-result validation. A
  baseline published between reads wins; an absent second read lets the
  operation linearize before any later publication.
- A trusted cache service restores into an empty cache root or performs
  per-object no-replace merge. A preexisting identical object is accepted;
  different bytes at the same immutable path fail restore. Results restore
  before baselines, and a restored baseline whose target is absent is corrupt.
  Ordinary archive extraction may not overwrite or merge divergent baseline
  trees, so restore order cannot choose a winner.
- Evaluation must override reuse internally rather than trusting repository
  config. Otherwise trials can collapse to one carried result and falsely pass
  stability metrics.
- An analyzer model catalog does not imply a verifier model catalog.
  `provider_source = "analyze"` receives the selected complete analyze
  descriptor; `override` retains its existing separate descriptor.

Failure priority:

1. invalid config/model descriptor;
2. invalid current packet/report input;
3. corrupt baseline or target result;
4. review-lock acquisition and complete post-lock baseline recheck;
5. required qualification unavailable for the final selected result set;
6. completeness, call, cost, and runtime preflight;
7. analysis-lock, provider, and normalization work for genuine misses;
8. result/baseline/report publication.

No later provider success may hide an earlier configuration, cache-integrity,
or qualification failure.

## Rollout And Rollback

Rollout order:

1. Promote and review the spec changes.
2. Ship readers for legacy result objects and analysis-report schemas 3/4,
   plus new review identity and baseline validation.
3. Ship baseline writers and schema-5 report production while the repository
   still uses its current model.
4. Run one `read-write` warmup with the old selected model. Valid exact hits
   create baselines without provider calls.
5. Add reviewed alternate model descriptors.
6. Switch Backstitch dogfood to `cache_mode = "read-write"` and permit ambient
   `LLM_MODEL`/CLI model selection.
7. Observe exact hits, carried results, provider calls, producing identities,
   and cost estimates in the schema-5 report before relying on the default.

Rollback:

- Older binaries ignore none of the new strict keys, so config rollback must
  remove `result_reuse` and `[analyze.models]` before or with binary rollback.
- Schema-5 reports are not readable by older binaries. They are disposable run
  artifacts; retain schema-3/4 readers in the new binary, but do not require
  backward writers.
- Baseline objects are additive and ignored by old binaries. They may remain
  in the cache on rollback.
- Existing `results/<analysis_key>.json` objects remain unchanged and usable.
- Reverting to `cache_mode = "require"` restores zero-call dogfood behavior but
  causes misses for new/changed packets.

There is no source or database migration and no destructive cache rewrite.
The new baseline format is an additive compatibility surface, not a one-way
data door.

## Dependency-Ordered Implementation Tasks

### Slice 0: Spec promotion and contract fixtures

1. Reconcile [CFG-5]/[CFG-6], [SEM-3]/[SEM-4]/[SEM-9], and
   [EVC-6]/[EVC-9.1].
2. Add exact JSON/TOML contract fixtures for review identity, baseline object,
   model catalog, and schema-5 report.
3. Run explicit self-check and traceability gates before runtime code.

Gate: a zero-context reviewer can derive every cache path, key preimage,
selection order, counter, failure class, and qualification rule without
reading this plan as a second contract.

### Slice 1: Settings and model descriptor catalog

1. Write failing settings tests for both reuse values, packaged default,
   invalid values, catalog exactness, extend replacement, duplicate selectors,
   partial descriptors, atomic flat-descriptor replacement, generic-option
   rejection for every non-model descriptor leaf, selector behavior for both
   CLI model forms, unknown CLI/env models in cached mode, and cache-off
   fallback.
2. Add immutable typed model-descriptor settings.
3. Resolve the winning model and descriptor inside `resolve_config()` after
   environment and CLI model precedence.
4. Project selected descriptor and sorted available model names in
   `config show`.
5. Keep dynamic catalog children out of generic `--option`; model selection
   remains the only environment/CLI catalog operation.

Gate: public CLI/config tests prove CLI > environment > file model selection
with one resolver call and no stale descriptor field.

### Slice 2: Review identity

1. Write mutation tests proving each review-contract field changes
   `review_key`, provider-only changes do not, and canonical bytes are stable.
2. Add `ReviewIdentity` and construct it in the same module/function family as
   `InferenceIdentity`.
3. Derive inference and review contracts from one canonical owner to prevent
   field drift.

Gate: deleting either identity module would force all key-construction
complexity back into callers; no caller hand-builds a review contract.

### Slice 3: Immutable baseline storage

1. Write real-filesystem red tests for baseline hit, miss, publication,
   concurrent different-model first writer, crash gap, absent target,
   mismatched review key, corrupt result, legacy exact hit, require-mode
   publication between its two reads, and bounded warmup.
2. Add strict baseline encode/read/validate/publish helpers inside
   `semantic_cache.py`.
3. Publish result before baseline with the existing immutable no-replace
   primitive.
4. Add the review-key lock/guard/audit state machine and exact cleanup target;
   enforce the only nested order, review lock then analysis lock.
5. Add evidence-stable and exact-inference lookup without changing verifier
   object selection.
6. Ensure `require` performs no write and no adapter construction.

Gate: run concurrent and corruption tests repeatedly with the real filesystem.
No mocks may replace path publication, link/no-replace behavior, result
validation, or race resolution.

### Slice 4: Analysis orchestration, budgets, and reports

1. Make read-only inspection classify exact hits, carried hits, and misses
   before provider-call/cost preflight.
2. Preserve original analysis keys and provider identities through result
   normalization and policy projection.
3. Produce and validate analysis-report schema 5 with selected inference,
   per-result source/provenance/object-hash rows, and reconciled top-level,
   kind, and provider counts. Pass the ordered selected result envelopes into
   report validation instead of asking the report to attest to itself.
4. Retain strict schema-3/4 readers and reject hybrid/unknown shapes.
5. Pass an ordered non-report selection-event stream from the actual
   cache/live branches and validate every persisted source class against it.
6. Add mutation tests for forged selected provider, result-object hash,
   inference preimage, review key, provenance, source class, aggregate count,
   and provider group.
7. Force exact-inference behavior in semantic evaluation and replay.

Gate: one changed packet under a new model creates exactly one provider call;
unchanged packets carry their prior results; the report names both producer
identities and all counts reconcile.

### Slice 5: Qualification and verification

1. Write failing tests for advisory carried results, current verification of a
   carried analyzer claim, exact-selector failure with a foreign analyzer
   identity, and exact-mode current-model success.
2. Move required qualification validation late enough to inspect selected
   analyzer result identities but keep it before provider work/publication.
3. Emit the existing structured unavailable-qualification problem with every
   foreign identity named in canonical `unqualified_analyzer_providers`
   details.
4. Do not add multi-artifact qualification lookup.

Gate: no test mocks qualification loading, cache selection, or policy
resolution. A foreign carried result can never become blocking under current
model qualification.

### Slice 6: Dogfood and default-command integration

1. Add authoritative alternate model descriptors required by the repository.
2. Set repository analyze cache mode to `read-write`; retain call/runtime/cost
   ceilings and exact cost-source review dates.
3. Finish selected-default argument forwarding from the configured-default
   plan so `backstitch .` and `backstitch --model MODEL` reach analyze.
4. Prove ambient `LLM_MODEL` remains set, selects its catalog descriptor, and
   carries unchanged baseline results without clearing the environment.
5. Prove a new/changed packet uses the selected model and publishes its own
   immutable result/provenance.

Gate: the repo-specific config-show probe succeeds with ambient `LLM_MODEL`;
controlled adapters prove mixed old/new model behavior without live traffic.

### Slice 7: Documentation, acceptance, and final review

1. Update README model-selection/cache semantics and explain evidence-stable
   versus exact-inference behavior.
2. Update implementation docs and repository map with baseline ownership,
   report schema, model catalog, and qualification boundary.
3. Audit trusted cache workflows so each restore targets an empty root or uses
   per-object no-replace merge, restores results before baselines, and never
   layers divergent archives.
4. Add black-box acceptance probes for config selection, carried reuse,
   changed evidence, exact override, corruption, and no traceback.
5. Run independent reviews after storage slice, qualification slice, and full
   diff; disposition every finding.

Gate: all Definition of Done commands below pass and review has no unresolved
P1/P2 finding.

## Testing Plan

| Layer | Required proof |
|------|----------------|
| Identity unit | Exact review-contract bytes; provider exclusion; every included-field mutation |
| Settings unit | Enum/default/catalog/precedence/extend/unknown/partial/cost validation |
| Cache unit | Real immutable files, serialized first-writer race, lock cleanup, restore conflict, corruption, legacy compatibility, no full scan |
| Analysis integration | Exact/carried/miss lookup, one changed packet call, independently recomputable mixed-producer report |
| Qualification integration | Advisory foreign carry, blocking foreign carry exit 2, exact current success |
| Eval integration | Trials and replay always exact; no baseline can reduce calls or flips |
| CLI subprocess | `LLM_MODEL`, `--model`, config show, exit classes, no traceback |
| Acceptance | Baseline reuse, changed evidence, corruption, no credentials/provider on require hits |
| Self-corpus | Explicit hermetic `backstitch check --repo-root .`; controlled semantic dogfood |

Anti-mocking rules:

- Use real temporary cache directories and canonical cache objects.
- Use the public resolver and CLI parser for precedence tests.
- Mock only the external provider adapter after all local identity, cache,
  budget, and qualification preflight.
- Never mock `build_inference_identity`, review identity, cache inspection,
  baseline validation/publication, report validation, or policy resolution.
- Concurrency tests use real processes or threads against one cache root, not
  ordered fake calls.
- The different-model race test uses a barrier before review-lock acquisition,
  allows either model to win, and asserts one provider call, one baseline,
  byte-stable replay, and loser use of the winner. A second case makes the
  winner foreign to a strong qualification selector and proves the waiter
  fails before a second provider call.
- A multi-packet race makes the foreign baseline appear on the last canonical
  packet and proves sorted acquisition plus the all-result qualification
  preflight causes zero provider calls from the losing run.
- The require-mode race test pauses after exact-result validation, publishes a
  valid baseline, resumes the second read, and proves the baseline wins. Its
  negative control leaves the second read absent and proves exact-result
  return linearizes before later publication.

## Verification And Definition Of Done

Targeted gates:

```bash
uv run pytest tests/test_semantic_settings.py tests/test_settings.py -q
uv run pytest tests/test_semantic_cache.py -q
uv run pytest tests/test_semantic_analysis.py tests/test_semantic_reports.py -q
uv run pytest tests/test_semantic_eval.py -q
uv run pytest tests/acceptance/test_probe_analysis.py \
  tests/acceptance/test_probe_semantic_replay.py -q
```

Repository gates:

```bash
uv run ruff check backstitch tests
uv run mypy backstitch
uv run pytest -n auto -m "not live_llm and not benchmark"
uv run backstitch check --repo-root . --show-suppressions
git diff --check
```

Observed requirements:

- explicit self-check exits `0` with zero errors and warnings;
- every governed suppression has a valid declaration and nonblank rationale;
- schema-3/4 report compatibility and legacy exact cache hits pass;
- schema-5 mutation cases reject false selected-provider, result-object,
  producer, carry, and aggregate claims;
- evidence-stable unchanged packets make zero calls after warmup;
- one changed packet under a different selected model makes one call;
- carried results retain old provider identity and new results use the selected
  descriptor;
- exact-inference model change misses;
- changed epoch prevents carry without deleting old objects;
- corrupt baseline/target exits `2` without provider fallback;
- divergent cache archives cannot overwrite or select a baseline by restore
  order;
- `require` baseline hits construct no adapter and make zero calls;
- qualification never transfers across analyzer identity;
- evaluation trials never consume ordinary baselines;
- no live-LLM or benchmark result is claimed unless run explicitly and
  recorded.

## Independent Review Loop

Review 1, after this plan/spec slice:

- challenge whether review identity includes too much or too little;
- challenge first-writer baseline semantics and restore/partial-cache behavior;
- challenge model-catalog merge and precedence;
- challenge report count reconciliation and schema compatibility;
- challenge qualification and evaluation isolation;
- look for an unbounded scan, hidden mutable index, false provenance, silent
  policy downgrade, or provider work before preflight.

Review 2, after Slice 3:

- inspect real filesystem race and corruption behavior;
- verify result-first/baseline-second publication;
- verify review-to-analysis lock ordering, cleanup, timeout, and deadlock
  resistance;
- verify legacy exact paths remain unchanged.

Review 3, after Slice 5 and before completion:

- inspect the complete diff against [CFG-5]/[CFG-6], [SEM-3]/[SEM-4]/[SEM-9],
  and [EVC-6]/[EVC-9.1];
- rerun adversarial acceptance probes;
- require explicit disposition for every finding.

## Review Log

### 2026-07-28: plan/spec review

Verdict: pass after two revision rounds. All P1/P2 findings below were
accepted and closed; the final reviewer found no reopened locking,
qualification, identity, descriptor, report-validation, or restore issue.

| Finding | Disposition |
|---------|-------------|
| Qualification could not fail before provider work when two models raced without a review-key lock | Accepted. Serialize read-write baseline election with an outer review-key single-flight lock, recheck and qualify after acquisition, and permit only review-to-analysis nesting. |
| Schema-5 producer and carry totals were not independently recomputable | Accepted. Add selected inference plus an ordered per-result inference/provenance/source ledger and mutation tests. |
| Catalog children were atomic but the flat descriptor and generic CLI leaves were not | Accepted. Make the complete flat descriptor an atomic non-packaged file-layer group; reserve non-model descriptor leaves from generic `--option`; retain `--option analyze.model` only as a selector equivalent to `--model`. |
| Plan review-contract fixture added `prompt.kind`, contrary to the inference identity | Accepted. Remove `kind` and pin the exact existing canonical JSON bytes. |
| Mergeable cache restore could overwrite divergent baselines | Accepted. Require empty-root restore or per-object no-replace merge, results before baselines, with divergent bytes failing closed. |
| Immutable result envelopes could not prove `live` versus `exact-cache` | Accepted. Add ordered non-report operational selection events created at the runtime selection branch and require report validation to match them. |
| Require-mode one-read fallback could return an exact result after a baseline became durable | Accepted. Use baseline read, exact validation, baseline re-read; the second baseline wins and an absent second read is the linearization point. |

### 2026-07-28: implementation final review

Verdict: pass after all findings were accepted, implemented, and re-reviewed.

| Finding | Disposition |
|---------|-------------|
| Bare leading-path shorthand failed when global config controls preceded the path | Accepted. Preserve leading `--config`, `--no-config`, and `--option` groups while parsing the first remaining path as `--repo-root`; subprocess and one-resolution tests cover the forms. |
| Review-lock and nested analysis-lock waits could outlive the absolute command deadline; an overlong provider return could still publish | Accepted. Cap every evidence-stable blocking timeout by the remaining command deadline, check immediately after provider return, and prove that timeout paths publish no baseline (and no new result after provider overrun). |
| Trusted semantic workflow caches omitted the new baseline tree | Accepted. Restore, prepare, and save `baselines/` with packets, results, and verifier results in both semantic workflows; workflow contract tests enumerate all four trees. |
| Foreign-producer qualification used a fabricated authority and did not prove the all-lock race | Accepted. Generate and authoritatively reload a real enforce-mode report from the reviewed 20-case corpus. A real-filesystem two-packet race proves the foreign winner owns both sorted review locks, publishes both baselines, and the qualified waiter makes zero calls before failing with the foreign provider named. |

## Observed Verification

Observed in the final worktree on 2026-07-28:

- `uv run pytest -q`: pass.
- Focused semantic/cache/report/eval/settings/CLI/release workflow suite: pass.
- `uv run pytest tests/acceptance -q`: 45 passed.
- `uv run ruff check .`: pass.
- `uv run mypy backstitch`: 42 source files, no issues.
- `git diff --check`: pass.
- `uv run backstitch check --repo-root . --show-suppressions`: exit 0;
  121 spec sections, 296 mappings, 376 code refs, 794 edges, 8 invariants,
  16 binds, and zero errors, warnings, or infos; all 192 governed suppressions
  display declarations and nonblank rationales.
- `uv run backstitch config show --repo-root .`: repository default is
  `analyze`; identity is `pkg:service/openai.com/gpt-5.4-mini`; transport is
  `gpt-5.4-mini`; cache mode is `read-write`; reuse is `evidence-stable`.
- Controlled public-dispatch tests prove `backstitch .` and
  `backstitch --model gpt-5.4-mini` preserve deterministic preflight,
  argument forwarding, and one settings resolution without live traffic.

## Out Of Scope

- A source-controlled adjudication ledger.
- Mutable replacement of a baseline under one review key.
- Reusing a result after packet, prompt, request, contract, or epoch changes.
- Mixing fields from old and new inference results.
- A catalog of qualification artifacts for several analyzer identities.
- Verifier baseline reuse or verifier-cache redesign.
- Unbounded legacy-cache migration or full result-tree scans.
- Fine-grained cache pruning and concurrent whole-root deletion.
- Automatic provider pricing discovery from network calls.
- Treating a model change as proof that an old result is correct.

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|

## Fresh-Eyes Review Checklist

- Can a zero-context implementer write the exact review-key preimage?
- Is the carried unit unmistakably the complete original result/provenance?
- Can two concurrent model runs choose only one stable baseline?
- Is review-to-analysis the only nested lock order, including cleanup paths?
- Can a partial cache restore ever select another result silently?
- Does exact-inference preserve current cache semantics?
- Does changing search epoch create a new baseline without deleting history?
- Can cached model precedence ever retain another model's revision or prices?
- Are all report counters and producer identities independently recomputable?
- Can mutation of any result-source preimage or grouping survive validation?
- Can current-model qualification ever authorize a foreign carried result?
- Are evaluation trials isolated from ordinary evidence-stable baselines?
- Is rollback possible without rewriting existing result objects?
- Do tests keep the filesystem, resolver, cache validation, and qualification
  seams real?

# GPT-5.6 Luna Responses Migration Plan

Date: 2026-08-23

Status: active; implementation complete and locally verified; independent
implementation review PASS; remote Linux/macOS/Windows CI evidence pending

Class: 5 with Class 4 hardening. This changes Backstitch's public
configuration contract, inference identity vocabulary, provider wire path,
runtime dependency floor, applied dogfood model, release qualification, and
governing specs.

Plan type: implementation with spec revision

Hardening: required. The change crosses config parsing, immutable identity,
provider serialization, cache/report readers, live qualification, dependency
resolution, CI, and release boundaries.

## Goal

Move Backstitch's committed semantic-analysis default from GPT-5.4 mini to
GPT-5.6 Luna at `max` reasoning effort, using `llm` 0.33's OpenAI Responses
adapter and the newer OpenAI client API.

Make the smallest coherent contract change that supports providers whose
accepted request fields are not known until model selection. Keep one request
capability schema, make request-field absence real, and continue to validate a
committed descriptor before provider work. Do not build a generic provider
abstraction, a second schema, or time-based evidence expiry.

## Requested Outcomes

1. Backstitch's applied default resolves stable identity
   `pkg:service/openai.com/gpt-5.6-luna` to raw selector `gpt-5.6-luna`, sends
   `reasoning_effort = "max"`, and omits temperature and seed.
2. The supported request vocabulary has exactly five fields:
   `json_mode`, `temperature`, `seed`, `max_tokens`, and `reasoning_effort`.
   All five live in the existing capability schema version 1.
3. Omitting `reasoning_effort` means accepting the provider's default. There
   is no sentinel string or boolean for omission.
4. Top-level temperature and seed settings become optional. Packaged defaults
   omit both. The applied Luna descriptor forbids both.
5. The production Luna call uses the Responses API. The logical
   `max_tokens` setting becomes wire `max_output_tokens`; reasoning effort
   becomes `reasoning.effort`; no reasoning summary, temperature, or seed is
   sent.
6. Backstitch accepts `llm` 0.33's generated schema envelope with
   `strict = false` and retains its own closed, evidence-bound normalizer as
   the trust boundary.
7. Semantic evidence does not expire because a model is old or a fixed number
   of days elapsed. Existing `result_reuse = "evidence-stable"` behavior stays
   intact. A model selector change alone does not invalidate a baseline.
8. Release qualification is event-triggered. A release candidate proves the
   current Luna request and the protected GPT-5.5 override live, with at most
   one provider call per descriptor, two total, and a hard $0.10 ceiling. No
   persisted qualification receipt or seven-day freshness rule is added.
9. The dependency and request changes remain portable across the existing
   Linux, macOS, and Windows binary-wheel CI matrix.

## Decisions And Scope Boundary

This is an evolutionary change to the current design:

- Keep `capability_schema_version = 1`. Change its one unfrozen closed shape
  from four request fields to five. Do not add schema v2 or parallel readers.
- Keep the existing selected descriptor, `ResolvedInference`, lazy adapter
  factory, analyzer/verifier split, and immutable identity owners.
- Extend `EffectiveRequest` and `RequestIdentity` with optional
  `reasoning_effort`. Append the field so existing positional construction of
  the first four fields remains source-compatible during the migration.
- Keep `max_tokens` as Backstitch's provider-neutral logical name. The adapter
  owns the Responses wire spelling `max_output_tokens`.
- Make `temperature`, `seed`, and `reasoning_effort` optional config leaves.
  Absence means absence. Do not add an `"omit"` value or infer omission from a
  model name.
- Keep `json_mode` and `max_tokens` required in current analyze and enabled
  verify settings.
- Keep model capabilities in reviewed committed config. `llm` option-model
  introspection may detect whether the local adapter can serialize an option,
  but it is not provider capability authority and cannot rewrite a descriptor.
- Keep the raw stable-model split and evidence-stable cache selection. Do not
  change result, cache-object, report, packet, analysis-contract, or review-
  contract version numbers.
- Keep legacy adapter constructors for this slice. Production continues to
  use `ResolvedInference`; redesigning the overloaded compatibility surface is
  separate work.
- Keep verification disabled in the applied config. Make its dormant full
  table Luna-compatible by omitting temperature, seed, and reasoning effort.
- Keep the protected GPT-5.5 qualification override. Its Responses-compatible
  request omits temperature, seed, and reasoning effort.

The adapter serialization change increments Backstitch's provider adapter
version from 3 to 4. This gives the new wire behavior a distinct exact
inference identity. `llm` distribution version and the request projection also
remain in the existing identity.

## Source Documents

Governing repository sources:

- `docs/program-theory.md`
- `docs/specs/01-development-documentation-operating-model.md` [DOM-5],
  [DOM-10], [DOM-11], [DOM-15]
- `docs/specs/02-backstitch-core.md` [SC-7], [SC-10], [SC-13], [SC-17]
- `docs/specs/03-backstitch-configuration.md` [CFG-5.1], [CFG-6.5]
- `docs/specs/06-semantic-gates.md` [SEM-3], [SEM-4], [SEM-9]
- `docs/specs/07-verification-and-evidence-cases.md` [EVC-3.1], [EVC-5],
  [EVC-10.1]
- `docs/agent-context/runbooks/writing-plans.md`
- `docs/agent-context/runbooks/hardening-plans.md`
- `docs/agent-context/runbooks/testing-patterns.md`
- `docs/agent-context/runbooks/adversarial-acceptance-probes.md`
- `docs/agent-context/runbooks/review-loops-and-agent-bootstrap.md`
- `docs/agent-context/runbooks/maintaining-traceability.md`

Provider and dependency evidence reviewed while forming this plan:

- OpenAI GPT-5.6 Luna model page:
  <https://developers.openai.com/api/docs/models/gpt-5.6-luna>
- OpenAI latest-model guide:
  <https://developers.openai.com/api/docs/guides/latest-model>
- `llm` 0.33 release and installed source behavior
- live bounded OpenAI probes recorded in the plan baseline below

## Baseline And Observed Facts

Plan-authoring baseline: commit
`a28b66fb74adc34b01d3fab402b0bb871ec80b6b`.

At that baseline:

- `pyproject.toml` declares `llm>=0.31`; `uv.lock` resolves `llm` 0.31.1 and
  OpenAI Python 2.45.
- Backstitch's applied descriptor selects GPT-5.4 mini with temperature 0,
  seed 42, and 512 maximum output tokens.
- The capability schema and all closed readers enumerate four request fields.
- `backstitch/analysis_llm.py` adapts GPT-5-family Chat Completions by patching
  `max_tokens` to `max_completion_tokens`.
- `backstitch/defaults.toml` supplies temperature 0 and seed 42 even when a
  repository does not configure them.
- `bin/release.py` already owns the protected live-provider precheck. No code
  produces the qualification receipt shape described by the specs.
- The existing Linux, macOS, and Windows build matrix is the portability
  authority for locked dependency wheels. Windows is not locally available.

Bounded provider and local-adapter probes established:

- `llm.get_model("gpt-5.6-luna")` under `llm` 0.33 resolves to
  `llm.default_plugins.openai_models.Responses`.
- Its option model accepts reasoning efforts `none`, `minimal`, `low`,
  `medium`, `high`, `xhigh`, and `max`.
- GPT-5.6 Luna rejects Chat Completions with `max` effort.
- GPT-5.6 Luna Responses rejects seed and temperature.
- GPT-5.6 Luna Responses accepts `max` effort, no temperature or seed, and a
  JSON schema request.
- A protected GPT-5.5 Responses request accepts the same omission pattern with
  no explicit reasoning effort.
- `llm` 0.33 maps logical `max_tokens` to `max_output_tokens`, maps reasoning
  effort to `reasoning.effort`, emits schema `strict = false`, and finalizes
  Responses calls with `store = false`.
- Unless `hide_reasoning = true`, `llm` requests a reasoning summary for
  reasoning models. Backstitch does not consume that summary.
- `llm` exposes temperature and seed in the Luna option model even though the
  provider rejects them. Wrapper introspection therefore proves local
  serialization support only, not provider acceptance.

These probes are design evidence, not a substitute for the hermetic and live
qualification tests required below.

## Target Applied Descriptor

The implemented `pyproject.toml` analyze descriptor will resolve to:

```toml
[tool.backstitch.analyze]
backend_id = "llm"
plugin_id = "openai"
plugin_distribution_name = "llm"
model = "pkg:service/openai.com/gpt-5.6-luna"
adapter_model_id = "gpt-5.6-luna"
model_revision = "gpt-5.6-luna"
capability_schema_version = 1
capability_revision = "openai-gpt-5.6-luna-2026-08-23"
maximum_input_bytes = 1600000
json_mode = "require"
max_tokens = 16384
reasoning_effort = "max"
input_cost_microusd_per_million_tokens = 400000
output_cost_microusd_per_million_tokens = 1800000
input_token_overhead = 256
cost_rate_source = "OpenAI GPT-5.6 Luna model page, reviewed 2026-08-23; conservative rates include the published long-prompt multiplier"

[tool.backstitch.analyze.request_constraints.json_mode]
presence = "required"
allowed_values = ["require"]

[tool.backstitch.analyze.request_constraints.temperature]
presence = "forbidden"

[tool.backstitch.analyze.request_constraints.seed]
presence = "forbidden"

[tool.backstitch.analyze.request_constraints.max_tokens]
presence = "required"
minimum = 1
maximum = 16384

[tool.backstitch.analyze.request_constraints.reasoning_effort]
presence = "optional"
allowed_values = ["max"]
```

There is no dated Luna snapshot in the reviewed model catalog, so the raw
selector is also the declared revision. A later dated snapshot is an atomic
descriptor update, not runtime discovery.

The cost ceiling stays at its existing applied value. The rates use the higher
conservative values needed to cover the provider's published long-prompt
pricing tier rather than only the headline short-prompt rate.

The protected GPT-5.5 qualification override remains exact:

```toml
model = "pkg:service/openai.com/gpt-5.5"
adapter_model_id = "gpt-5.5-2026-04-23"
model_revision = "gpt-5.5-2026-04-23"
capability_schema_version = 1
capability_revision = "openai-gpt-5.5-responses-2026-08-23"
maximum_input_bytes = 1600000
json_mode = "require"
max_tokens = 1024
maximum_estimated_cost_microusd = 100000
input_cost_microusd_per_million_tokens = 5000000
output_cost_microusd_per_million_tokens = 30000000
input_token_overhead = 256
```

Its five capability children require JSON and max tokens, forbid temperature,
seed, and reasoning effort, and bound max tokens from 1 through 16,384. The
qualification request therefore accepts the provider's reasoning default. The
existing reviewed 2026-07-29 GPT-5.5 cost source remains in the generated live
config. With the 1,024-token GPT-5.5 cap and 16,384-token Luna cap, the
conservative two-call estimate must still pass the $0.10 preflight before
traffic.

### Qualification Outcome Decision Table

Qualification is a protected pytest/release process, not a new product
artifact or public output schema. Each descriptor produces one of these
operator-facing results:

This table governs the `BACKSTITCH_LIVE_LLM_KIND=openai` branch only.
`bin/release.py` also invokes the same live test with
`BACKSTITCH_LIVE_LLM_KIND=local` after its existing local-model prewarm. That
local contract/prewarm lane keeps its separate invocation, model, effective
request, packet count, and budgets. Its descriptor receives only the mandatory
five-constraint schema migration, with reasoning effort forbidden. The global
`llm` lock and adapter-version change may re-key its exact inference identity.
Its calls do not count against the OpenAI branch's two-call ceiling.

| Result | Exact condition | Provider calls | Release effect |
|---|---|---:|---|
| `compatible` | The exact frozen request is accepted, the returned body passes Backstitch's closed normalizer, and immediate immutable-cache replay returns the same canonical result with zero more calls. | exactly 1 | descriptor passes |
| `incompatible` | The installed adapter cannot serialize the exact selected request/schema; the provider returns an exact-request rejection such as HTTP 400, 404 for the selected model/operation, or 422; or a successful HTTP response cannot satisfy Backstitch's closed response/evidence contract. | 0 or 1 | blocks release |
| `unavailable` | Credentials are missing or rejected; authorization is absent; the provider rate-limits the call; or DNS, TLS, connection, timeout, HTTP 5xx, or equivalent service failure prevents an acceptance decision. | 0 or 1 | blocks release |

An invalid descriptor, violated local cost/call preflight, corrupt cache, or
test/setup failure is a release-precheck configuration/error failure before an
outcome is established. It also blocks release and does not masquerade as
provider incompatibility. If an earlier descriptor fails, the process may stop
without calling the second descriptor; the ceilings remain upper bounds.

The pytest case passes only when both descriptors are `compatible`. Otherwise
it fails with a bounded, secret-free message prefixed `incompatible:`,
`unavailable:`, or `qualification error:` and names the stable/raw selection.
`bin/release.py` propagates that nonzero pytest exit. There is no machine-
readable receipt, persisted status, or waiver based on which failure category
occurred.

## Proposed Spec Delta

Promotion strategy: **Strategy B, atomic activation**. These are edits to
already-active, already-mapped sections. Keeping their existing mapping blocks
while landing new normative behavior before conforming code would falsely
claim that the mapped implementation already satisfies the new contract.
Removing those mappings would create needless graph churn. After independent
review, the implementer edits the specs first in the working tree, then follows
T2 through T7 in dependency order, but lands no spec-only intermediate state.
The promoted text, unchanged mapping blocks, conforming code, tests, applied
config, dependency lock, and reciprocal backlinks land together and pass the
zero-warning gate as one activation slice.

### `docs/specs/02-backstitch-core.md` [SC-10]

Replace the current protected-qualification bullet, from `protected scheduled
qualification` through `satisfies the release receipt gate`, with:

> - every release candidate runs protected live qualification for the complete
>   committed default descriptor and the protected GPT-5.5 override through
>   their production stable/raw selections. A change to a selected model,
>   model revision, effective request, capability descriptor, adapter,
>   provider dependency, or qualification logic requires the same bounded
>   qualification before the changed contract is treated as release-ready.
>   One qualification event makes at most two generation calls total and at
>   most one per descriptor, with a hard $0.10 USD estimated-cost ceiling.
>   Each accepted call is immediately replayed from immutable cache with zero
>   provider calls. Provider unavailability is reported as `unavailable`, not
>   `incompatible`. Exact-request serialization/rejection or a provider-
>   accepted response that fails Backstitch's closed normalizer is
>   `incompatible`; missing/rejected credentials, absent authorization, rate
>   limiting, transport failure, timeout, and provider 5xx are `unavailable`.
>   Both block release, as do local qualification setup and preflight errors.
>   Neither outcome edits a descriptor. Elapsed time and
>   repository inactivity do not invalidate a prior semantic evaluation and
>   do not create a process violation. Qualification is execution evidence for
>   the current release event; Backstitch does not define or persist a dated
>   capability-receipt artifact

Add these firing-test requirements to the same section:

> - one hermetic test using the real installed `llm` Responses adapter and a
>   test-owned HTTP transport proves the Luna request wire shape, exactly one
>   call, and the independent closed response normalizer
> - qualification tests fire for compatible, incompatible, and unavailable
>   outcomes, the two-call and $0.10 ceilings, zero-call replay, and the release
>   precheck's unconditional invocation; selected descriptor/request fixtures
>   prove that a changed current contract is the contract exercised, and no
>   wall-clock-age case exists

Update the named models in the bullet from GPT-5.4 mini to GPT-5.6 Luna. Keep
the existing live-policy and acceptance-suite requirements unchanged.

### `docs/specs/03-backstitch-configuration.md` [CFG-5.1], [CFG-6.5]

In [CFG-5.1], retain the complete descriptor and generic-option ownership. Add
`reasoning_effort` to the known analyze and verify request leaves. It is a
normal request-value leaf, not a descriptor leaf, so a trusted static
`--option analyze.reasoning_effort '"max"'` may set it. Constraint descriptors
remain file-owned and atomic.

Replace [CFG-6.5]'s request-constraint vocabulary paragraph with:

> `request_constraints` is a closed mapping with exactly `json_mode`,
> `temperature`, `seed`, `max_tokens`, and `reasoning_effort`. Each authored
> TOML value is a closed record containing `presence` plus only its applicable
> constraint keys. `presence` is `required`, `optional`, or `forbidden`.
> `json_mode` uses nonempty duplicate-free `allowed_values` drawn from
> `require` and `off`; configured `prefer` is a resolution instruction and
> must resolve to one of those effective wire values before validation.
> `temperature` uses nonempty duplicate-free finite-number `allowed_values`.
> `seed` and `max_tokens` use integer `minimum` and `maximum`, with minimum no
> greater than maximum. `reasoning_effort` uses nonempty duplicate-free
> `allowed_values` drawn from `none`, `minimal`, `low`, `medium`, `high`,
> `xhigh`, and `max`. An allowed-value constraint omits both bounds. A range
> constraint omits `allowed_values`. A forbidden field omits all three
> constraint members. Unknown or inapplicable authored keys are invalid. The
> resolver expands authored TOML into [SEM-3]'s one exact runtime record by
> inserting null for every omitted inapplicable member. Thus TOML needs no
> null literal and the normalized descriptor has one closed canonical shape.
> A required field must be present in the frozen effective request; a
> forbidden field must be absent; an optional field is validated when present.
> Backstitch validates but never silently corrects, adds, or removes an
> explicitly configured incompatible value.

Add this request-value paragraph immediately after it:

> `json_mode` and `max_tokens` are required request settings in analyze and an
> enabled verifier. `temperature`, `seed`, and `reasoning_effort` are optional
> request settings. When no effective config layer supplies an optional
> setting, it is absent from `EffectiveRequest`, `RequestIdentity`, and the
> provider request. Absence of `reasoning_effort` accepts the provider default;
> no sentinel value represents omission. Ordinary scalar precedence applies
> when a layer supplies an optional value. Because this schema has no deletion
> sentinel, a child config cannot erase an optional value inherited through
> `extend`; it must stop extending that source or the inherited value must
> satisfy the newly selected descriptor. An incompatible inherited value fails
> with its exact config key before provider work.

Update every exact descriptor-field list and verify override statement to say
that each `request_constraints` child set contains the five fields above.
Keep `capability_schema_version` exactly integer 1.

### `docs/specs/06-semantic-gates.md` [SEM-3]

Change the example request object to:

```json
"request": {
  "json_mode": "require",
  "max_tokens": 16384,
  "reasoning_effort": "max"
}
```

Replace the `EffectiveRequest` vocabulary paragraph with:

> `EffectiveRequest` makes a presence decision for every known request field:
> `json_mode`, `temperature`, `seed`, `max_tokens`, and `reasoning_effort`. A
> present field carries its canonical validated value. An absent optional or
> forbidden field is recorded as absent by the immutable resolved value and is
> omitted from both the transport body and the closed `RequestIdentity` JSON
> projection. Because the field vocabulary is closed, omission is an
> unambiguous identity decision, not an adapter default. Adding
> `reasoning_effort` to the vocabulary does not add it to an existing logical
> request that omits it; such a four-field request keeps byte-for-byte request
> projection compatibility. A protocol serialization constant that is not a
> user request control is code-owned and must be covered by the keyed adapter
> version.

Replace the capability shape with:

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

State that the five constraint children are exact and that reasoning effort
uses [CFG-6.5]'s string domain. Keep descriptor authority, provenance, and
pre-provider validation unchanged.

Delete the normative `backstitch-capability-qualification` receipt schema and
its field-validation paragraphs. Replace them with:

> Live capability qualification is bounded release-process evidence, not
> semantic input or persistent Backstitch artifact authority. It executes the
> exact selected descriptor and frozen request under [SEM-9]/[SC-10]. Its
> outcome never edits a capability descriptor and never enters packet, prompt,
> request, inference, review, cache, result, report, or finding identity.
> Elapsed time alone therefore creates neither a cache miss nor a need to
> relabel historical results.

Add this adapter rule after the structured-output paragraph:

> The `llm` OpenAI Responses adapter may emit its supported JSON Schema
> envelope with `strict = false`. This is a generation aid, not authority.
> Backstitch does not patch a private provider builder to change that flag; the
> closed [SEM-5] normalizer independently rejects unknown fields, invalid
> values, and evidence outside the packet.

### `docs/specs/06-semantic-gates.md` [SEM-4]

Do not change the evidence-stable object or lookup contracts. Add one
clarifying sentence after the cross-provider carry-forward rule:

> A newer model selection, provider qualification observation, or passage of
> time does not by itself invalidate an evidence-stable baseline. Packet,
> prompt, request, analysis-contract, search-epoch, or normalization changes
> continue to re-key under [SEM-3]; explicit resampling continues to use
> `search_epoch`.

This migration changes the request vocabulary, effective Luna request, adapter
version, code, and governing spec. Affected exact inference and review keys may
therefore change under the existing rules. That is a substantive contract
change, not model-age invalidation. No cache migration or fallback probe is
added.

### `docs/specs/06-semantic-gates.md` [SEM-9]

Add optional `reasoning_effort = "max"` to the supported configuration
surface and replace the request rows in the normative value table with:

| Keys | Type and range |
|---|---|
| `json_mode` | required; `prefer`, `require`, or `off` |
| `max_tokens` | required integer excluding booleans, at least 1 |
| `temperature` | optional finite number from 0 through 2 |
| `seed` | optional integer excluding booleans, at least 0 |
| `reasoning_effort` | optional `none`, `minimal`, `low`, `medium`, `high`, `xhigh`, or `max`; absence accepts the provider default |

Replace the packaged-request-default sentence with:

> Packaged request defaults are exact: `json_mode = "prefer"` and
> `max_tokens = 512`. Packaged defaults omit `temperature`, `seed`, and
> `reasoning_effort`; their absence remains explicit through resolution.

Replace the protected qualification paragraph with:

> Every release candidate exercises one bounded accepted request for the
> committed default model and one for the committed GPT-5.5 override through
> their production stable/raw selections and capability descriptors. Each
> successful call is immediately replayed from immutable cache with zero
> provider calls. The complete event is capped at two provider calls, one per
> descriptor, and $0.10 USD estimated cost. Selected-model, revision, request,
> descriptor, adapter, provider-dependency, or qualification-logic changes
> require this proof before release. The release precheck invokes qualification
> unconditionally, so this rule needs no persisted change fingerprint.
> Exact-request serialization/rejection or accepted output that fails the
> closed normalizer is incompatible. Credential, authorization, rate-limit,
> transport, timeout, and provider-5xx failures are unavailable. Both block
> release, as do local setup/preflight errors. Neither result edits a
> descriptor or semantic
> identity. No elapsed-time limit applies and no dated qualification receipt
> is a Backstitch artifact.

Replace the qualification firing-test line that names `current` and
`older-than-seven-days` with compatible, incompatible, unavailable, bounded
call/cost, unconditional-release-invocation, selected-contract, and zero-call
replay cases. Remove all remaining
claims that a capability qualification receipt has a maximum age.

Record the applied dogfood default as GPT-5.6 Luna, max reasoning, 16,384
logical output tokens, and omitted temperature/seed. Retain
`result_reuse = "evidence-stable"`.

### `docs/specs/07-verification-and-evidence-cases.md` [EVC-3.1], [EVC-5], [EVC-10.1]

Mechanically replace each closed request-vocabulary notation:

```text
{json_mode, temperature, seed, max_tokens}
```

with:

```text
{json_mode, temperature, seed, max_tokens, reasoning_effort}
```

The notation names the closed vocabulary, not mandatory presence. The
canonical object omits each absent optional field.

In [EVC-5], add `reasoning_effort` as an optional enabled-verify request leaf.
Update the override descriptor example with the required fifth constraint
child. The provider-neutral example uses:

```toml
[tool.backstitch.verify.provider.request_constraints.reasoning_effort]
presence = "forbidden"
```

Replace the all-or-nothing enabled-shape statement with:

> An enabled or dormant-complete verifier contains every non-request base key
> shown above, required request keys `json_mode` and `max_tokens`, and zero or
> more optional request keys `temperature`, `seed`, and `reasoning_effort`.
> Provider constraints decide which optional fields may be present. A dormant
> table is complete when this shape and its selected provider descriptor are
> complete; omission of an optional request key is not partial configuration.

In [EVC-10.1], update `composition_request`, analyzer composition, verifier
composition, report loading, and equality checks to use the same five-field
closed vocabulary with absent optional fields omitted. No evaluation artifact
or report schema version changes.

Append this plan to each changed spec's `Related Plans` section:

> - `docs/plans/2026-08-23-gpt-5-6-luna-responses-plan.md`
>   (active implementation plan; request capabilities, Responses migration,
>   and release qualification)

## Context And Key Files

Core identity and config owners:

- `backstitch/semantic_identity.py`: `EffectiveRequest`, `RequestIdentity`,
  capability constraints, validation, request/review/inference contracts, and
  adapter version.
- `backstitch/settings.py`: known keys, immutable settings types, optional
  value parsing, descriptor parsing, verify shape, config rendering, and
  cross-field validation.
- `backstitch/defaults.toml`: packaged absence defaults and generic capability
  descriptor.
- `pyproject.toml`: runtime dependency, applied Luna descriptor, request, and
  dormant verifier.
- `uv.lock`: exact `llm`, OpenAI, HTTPX, and transitive dependency graph.

Provider and semantic owners:

- `backstitch/analysis_llm.py`: lazy model selection, option validation,
  schema call, Responses serialization behavior, and response provenance.
- `backstitch/semantic_analysis.py`: analyzer/verifier inference resolution.
- `backstitch/semantic_cache.py`: closed inference and review contract readers.
- `backstitch/semantic_reports.py`: current and historical report readers.
- `backstitch/semantic_eval_reports.py`: evaluation composition readers.
- `backstitch/doctor.py`: provider-free option/capability inspection.

Qualification and delivery owners:

- `tests/live/test_live_llm.py`: protected live request and exact qualification
  selection.
- `bin/release.py`: mandatory release-precheck command and its bounded local
  OpenAI transport fixture.
- `.github/workflows/ci.yml`: hermetic tests and binary-wheel platform matrix.
- `tests/test_release_script.py` and `tests/test_release_workflow.py`: release
  command and workflow authority.

Documentation owners:

- `README.md`
- `docs/implementation/04-backstitch-style-traceability.md`
- `docs/implementation/07-deterministic-semantic-gate.md`

## Invariants And Constraints

1. **One schema.** Capability schema version 1 has exactly five request
   constraints after promotion. Four-child descriptors are invalid current
   configuration. There is no v1/v2 branch.
2. **One resolution.** Config resolution freezes field presence and values
   before adapter construction. The adapter never guesses a missing field from
   the selected model.
3. **Absence is identity.** An absent optional field is omitted from
   `EffectiveRequest.to_dict()`, `RequestIdentity.to_dict()`, and the provider
   body. No null or sentinel enters a canonical request.
4. **Provider-neutral logical limit.** `max_tokens` remains the only public
   output-limit setting. Responses serialization changes only the wire name.
5. **Committed capabilities win.** `llm` introspection cannot add, remove, or
   override capability constraints and cannot perform credential or network
   work during resolution.
6. **Untrusted generation constraints.** JSON Schema `strict = false` is
   accepted only because Backstitch's own normalizer remains closed and
   evidence-bound.
7. **No silent fallback.** Provider rejection, missing adapter options, or a
   descriptor mismatch is exit 2. There is no Chat fallback, unstructured
   retry, request-field deletion, or lower reasoning retry under one identity.
8. **Evidence lifecycle.** Provider/model changes, qualification observations,
   and time do not by themselves invalidate evidence-stable baselines. Existing
   review-key inputs and `search_epoch` remain the invalidation/resampling
   mechanism.
9. **No artifact migration.** Existing artifacts that omit reasoning effort
   remain valid when their other bytes and version contracts are valid. Readers
   accept the one current closed vocabulary with optional omission.
10. **Bounded live work.** Qualification makes at most one call per descriptor
    and two total, costs at most $0.10, and replays accepted results with zero
    provider calls.
11. **Deterministic isolation.** `check`, `packets`, config resolution, and
    required-cache replay remain provider-free and credential-free.
12. **Cross-platform delivery.** The dependency lock and wheel build must pass
    the existing Linux, macOS, and Windows matrix. A local macOS pass cannot
    close the Windows gate.
13. **Release lane isolation.** The two-descriptor Luna/GPT-5.5 qualification
    applies only to the protected OpenAI branch. The existing local live-model
    invocation, prewarm, model, effective request, packet count, and budgets
    remain behaviorally unchanged. Its descriptor still migrates to the one
    five-field schema, and global dependency/adapter identity changes apply.
14. **No unrelated redesign.** The adapter compatibility constructors,
    provider abstraction depth, cache layout, report versions, evaluation
    corpus, and verification policy remain unchanged.

## Hidden Couplings And Failure Risks

- Request fields are independently closed in settings, identity, cache,
  report, evaluation-report, doctor, defaults, fixtures, and tests. Updating
  only the dataclass would make current writers disagree with readers.
- Optional settings interact with config `extend`, packaged defaults, dormant
  verify completeness, generic `--option`, config parity, `config show`, and
  flat/catalog descriptor selection.
- `RequestIdentity` participates in analysis keys, review keys, verifier keys,
  report composition, qualification selection, and cache validation. Field
  order and omission must remain canonical.
- The existing completion-token shim patches Chat adapters. Applying it to a
  Responses model would either fail or serialize the wrong wire key. Model
  family detection must stay local to the adapter and have a real-adapter test.
- `llm`'s option model overstates provider support for Luna temperature and
  seed. Treating introspection as provider truth would recreate the bug this
  change is intended to prevent.
- `hide_reasoning = true`, `store = false`, and the Responses schema envelope
  are wrapper serialization details. The adapter version must cover the
  code-owned behavior and tests must pin the observed wire body without
  patching private `llm` builders.
- Raising output tokens from 512 to 16,384 changes budget estimates and may
  expose overly tight local test server assertions. Cost preflight must still
  use configured ceilings and observed rates, not provider marketing aliases.
- GPT-5.5 qualification currently adds temperature and seed. Leaving that path
  unchanged would make release precheck fail even if Luna works.
- `llm` 0.33 upgrades OpenAI and HTTPX major versions. Wheel availability and
  transport behavior, especially on Windows, must be proved by CI rather than
  assumed from macOS.
- Removing time-current receipts can leave misleading spec references even if
  runtime has no artifact. A repository-wide search for the artifact name,
  seven-day wording, and age tests is part of the slice.

## Anti-Mocking Guidance

Use fakes only at the remote provider boundary.

- Settings tests use real TOML files, discovery, `extend`, CLI parsing, and
  immutable settings assembly.
- Identity and cache tests use the real canonical JSON and key owners.
- The hermetic wire test imports the installed `llm` 0.33 distribution,
  resolves the real Luna `Responses` model class, and routes its HTTP client to
  a test-owned transport or server. It must not replace `llm.get_model`, the
  model option class, Responses request builder, Backstitch adapter, settings,
  or normalizer.
- The test-owned transport may return a minimal valid Responses payload and
  count requests. It must capture the actual `/v1/responses` body.
- Live qualification uses real credentials and provider traffic only in the
  protected lane. Hermetic CI remains credential-free.
- Release tests may replace subprocess execution to inspect the exact command
  vector, but a separate integration proof runs the real bounded helper.
- Windows proof comes from the real CI environment and locked wheels, not a
  platform-string mock.

## Dependency-Ordered Tasks

### T0. Freeze Plan Authority And Independent Review

- Add this active plan and index row.
- Run an independent plan review against the code, specs, live helper, CI, and
  release command.
- Resolve every blocking finding in this plan. Do not implement until the plan
  review is PASS.
- Record the reviewed baseline and verdict in the review log.

### T1. Prepare The Governing Spec Delta Inside The Atomic Activation

- Apply the exact proposed changes to [SC-10], [CFG-5.1], [CFG-6.5], [SEM-3],
  [SEM-4], [SEM-9], [EVC-3.1], [EVC-5], and [EVC-10.1].
- Remove the capability qualification receipt schema, seven-day age rule, and
  age-oriented firing requirements. Do not remove unrelated source,
  candidate, or evidence receipts.
- Add Related Plans entries and exact implementation mappings for any new
  owners.
- Keep the existing mapped-section ownership in view while editing code. Do
  not land, commit, or call this spec-only working-tree state conformant.
- Record the single atomic activation baseline after T8 if the owner authorizes
  a landing commit.

### T2. Upgrade And Lock The Provider Stack

- Change the runtime dependency to `llm>=0.33,<0.34` and regenerate `uv.lock`.
- Confirm the lock resolves `llm` 0.33 and OpenAI Python 3 with one coherent
  HTTPX dependency graph.
- Add or update dependency policy tests so manifest, lock, and runtime cannot
  silently fall below the Responses-capable floor.
- Do not add a direct `openai` dependency unless `llm` no longer owns it.

### T3. Extend The Single Request And Capability Schema

- Add optional `reasoning_effort` to `RequestIdentity`, `EffectiveRequest`,
  `RequestConstraints`, settings types, normalization, canonical projection,
  validation, config rendering, and descriptor provenance.
- Accept exactly the seven reviewed reasoning strings. Reject booleans,
  numbers, blank strings, other strings, bounds on the string field, and
  allowed values on range-only fields.
- Make top-level analyze and verify temperature and seed optional. Add optional
  reasoning effort. Preserve required `json_mode` and `max_tokens`.
- Make packaged defaults omit temperature, seed, and reasoning effort. Give
  the packaged generic descriptor optional temperature/seed constraints and a
  forbidden reasoning constraint. This keeps its cache-off fallback broad
  without inventing a reasoning default.
- Update dormant-complete verify validation so optional request leaves may be
  absent without accepting a genuinely partial base/provider table.
- Update every closed field set and current/historical reader in semantic
  cache, reports, eval reports, doctor, and semantic analysis.
- Increment provider adapter version 3 to 4. Do not bump artifact or contract
  schema versions.

### T4. Implement Responses Serialization Through `llm` 0.33

- Keep lazy `llm` import and raw model selection.
- Include a present reasoning effort in required-option inspection and request
  options. Absence sends nothing.
- For the real `Responses` model path, rely on `llm` for
  `max_tokens -> max_output_tokens`, reasoning nesting, `store = false`, and
  response parsing.
- Pass `hide_reasoning = true` for every `llm` Responses model that exposes the
  public option, including Luna and the protected GPT-5.5 snapshot, so no
  unused reasoning summary is requested. Treat this as adapter-versioned code
  behavior, not a config key. Fail closed if a selected reasoning Responses
  model cannot express this reviewed serialization policy.
- Do not apply the Chat `max_completion_tokens` shim to a Responses model.
  Retain the shim only for supported Chat adapters.
- Continue to attach Backstitch's packet-local JSON Schema. Accept `llm`'s
  `strict = false`; do not patch `_build_responses_kwargs` or another private
  wrapper method.
- Keep the independent response and evidence normalizer unchanged except for
  tests needed to prove its authority.

### T5. Activate The Luna Descriptor And Compatible Verifier

- Replace the applied GPT-5.4 mini descriptor with the exact target descriptor
  above.
- Remove applied analyze temperature and seed. Set reasoning effort to `max`
  and logical max tokens to 16,384.
- Add all five constraint children. Forbid temperature/seed, require JSON and
  max tokens, and allow optional reasoning only at `max`.
- Keep `result_reuse = "evidence-stable"`, `search_epoch = "1"`, existing
  cache paths/modes, packet/runtime/call ceilings, and finding policy unless a
  measured test proves one is incompatible.
- Make the dormant full verify table omit temperature, seed, and reasoning
  effort so enabling it with `provider_source = "analyze"` is descriptor-
  compatible.
- Update README and implementation docs to explain the stable/raw identity,
  Responses ownership, optional field absence, committed capability authority,
  and evidence lifecycle.

### T6. Replace Age-Based Receipts With Event-Triggered Qualification

- Refactor the live helper's `BACKSTITCH_LIVE_LLM_KIND=openai` branch into one
  exact Luna qualification call and one exact GPT-5.5 qualification call. Use
  production resolution and adapter paths.
- Luna uses max reasoning, 16,384 logical output tokens, and no temperature or
  seed. GPT-5.5 omits temperature, seed, and reasoning effort.
- Keep the total call ceiling at two and estimated cost at or below $0.10.
- Immediately replay each accepted call from immutable cache and assert zero
  additional provider calls.
- Return concise compatible, incompatible, or unavailable process output and
  exit status according to the decision table above. Implement this as pytest
  pass/fail plus categorized, bounded failure messages, not a new JSON output
  contract. Both non-compatible outcomes and every local setup/preflight error
  block release. Do not write a qualification receipt, timestamp database, or
  freshness file.
- Keep `bin/release.py` as the release owner and update its exact command tests.
  If protected scheduled CI invokes the same helper, it shares the same rules
  but adds no time-validity contract.
- Preserve the separate `BACKSTITCH_LIVE_LLM_KIND=local` release invocation,
  background prewarm, model, effective request, packet count, and budget.
  Mechanically add its required fifth capability child with reasoning effort
  forbidden; accept the global dependency/adapter identity re-key. Add a
  regression test that OpenAI-branch changes do not otherwise alter or absorb
  that lane.

### T7. Complete Test And Fixture Migration

- Update all four-field descriptor fixtures to the one five-field capability
  schema. Choose constraints deliberately; do not bulk-insert one rule without
  considering the fixture model.
- Update explicit request identities only where the test intends reasoning.
  Existing four-argument positional identities must continue to mean reasoning
  absent.
- Update applied-config parity, config snapshots, report/eval compositions,
  semantic cache objects, doctor output, acceptance fixtures, performance
  fixtures, live helper fixtures, and release command fixtures.
- Add every firing test listed below before claiming the slice complete.

### T8. Full Verification, Cross-Platform CI, And Review

- Run the exact local gates below with observed results.
- Push only with owner authorization. Treat Linux, macOS, and Windows binary-
  wheel jobs as required verification after push; do not infer Windows success
  from local tests.
- Run an independent implementation review over the full diff and verification
  evidence. Resolve or explicitly answer every finding.
- Update this plan's execution, deviation, verification, and review logs.
- Close the index row only when implementation, docs, required CI, review, and
  an owner-authorized landing commit are complete.

## Testing Plan

### Settings And Capability Schema

Add firing tests for:

- all seven valid reasoning-effort values and each invalid type/value family;
- reasoning absent through packaged defaults, file config, `extend`, catalog
  selection, verify reuse, verify override, CLI option, and config parity;
- temperature and seed absent individually and together;
- required, optional, and forbidden reasoning constraints;
- missing fifth constraint, unknown sixth constraint, bounds on reasoning,
  duplicates, and invalid allowed values;
- Luna accepting max reasoning and rejecting absent required JSON/max tokens,
  temperature, seed, and non-max reasoning;
- absent reasoning accepting provider default for GPT-5.5 qualification;
- dormant-complete verify with omitted optional request leaves, and genuinely
  partial dormant tables still failing before provider work;
- `config show` rendering only present request values and all five normalized
  constraint children.

Primary files:

- `tests/test_settings.py`
- `tests/test_semantic_settings.py`
- `tests/test_cli_config.py`
- `tests/test_config_parity.py`
- `tests/test_doctor.py`

### Identity, Cache, And Reports

Add firing tests for:

- canonical request projection with reasoning present and absent;
- field order and unchanged bytes for an existing four-field request;
- analysis, review, and verifier keys changing when reasoning presence/value
  changes;
- model selector change alone retaining evidence-stable baseline reuse when
  packet, prompt, request, contract, and epoch are unchanged;
- this migration's changed request/adapter identity missing the old exact key
  without destructive cache migration or fallback;
- current cache/report/eval readers accepting absent or present reasoning in
  the one current vocabulary and rejecting unknown fields;
- no artifact schema-version bump;
- positional `RequestIdentity(json_mode, temperature, seed, max_tokens)`
  remaining reasoning-absent.

Primary files:

- `tests/test_semantic_identity.py`
- `tests/test_semantic_cache.py`
- `tests/test_semantic_reports.py`
- `tests/test_semantic_eval_reports_v3.py`
- `tests/test_semantic_analysis.py`
- `tests/test_semantic_verification.py`

### Hermetic Real-Adapter Wire Proof

Add one test that uses the real installed `llm` 0.33 Luna model and test-owned
HTTP transport. Assert exactly:

- model class is `llm.default_plugins.openai_models.Responses`;
- one request reaches `/v1/responses`;
- body `model` is `gpt-5.6-luna`;
- `max_output_tokens` is 16,384 and `max_tokens` plus
  `max_completion_tokens` are absent;
- `reasoning.effort` is `max` and reasoning summary is absent;
- temperature and seed are absent;
- `store` is false;
- the response format carries Backstitch's schema with `strict` false;
- the wrapper option model is inspected but the committed descriptor remains
  the authority;
- one valid closed response normalizes successfully;
- an unknown response field or out-of-packet evidence still fails in
  Backstitch's normalizer;
- no credential or external network is used.

Primary files:

- `tests/test_analysis_llm.py`
- a narrowly named fixture/helper beside the test if needed

### Live Qualification And Release

Add hermetic firing tests for:

- exact Luna and GPT-5.5 descriptors and request identities;
- compatible, incompatible, and unavailable outcomes;
- exact categorization for adapter serialization failure, HTTP 400/404/422,
  invalid successful response, missing/rejected credentials, authorization,
  rate limit, transport/TLS/DNS, timeout, and HTTP 5xx;
- invalid descriptor, cost/call preflight, corrupt cache, and setup errors
  remaining release-blocking errors rather than provider outcomes;
- at most one live call per descriptor and two total;
- hard $0.10 cost rejection before a provider call;
- accepted-call replay making zero more calls;
- unconditional live qualification in the release process, with the selected
  descriptor and request flowing into the exercised contract;
- no receipt file, timestamp, age parser, seven-day branch, or scheduled-age
  failure;
- release helper invokes the exact live command and propagates failure;
- both descriptors being required for a passing pytest/release precheck and
  either categorized failure producing a nonzero exit with no secret output;
- the existing local-kind release command and prewarm remaining separate and
  behaviorally unchanged apart from the global schema/dependency/adapter-
  identity migration, with its calls excluded from the OpenAI two-call ceiling;
- ordinary hermetic CI still collects the live test as one deliberate skip.

Then run one protected real-provider qualification with its bounded command
when credentials are available. Record only command, outcome, call count, cost
bound, model selections, and timestamp in the plan execution log. Do not add a
machine-readable receipt contract.

Primary files:

- `tests/live/test_live_llm.py`
- `tests/test_live_llm_helpers.py`
- `tests/test_release_script.py`
- `tests/test_release_workflow.py`
- `bin/release.py`

### Migration And Acceptance Inventory

Inspect and update at least:

- `tests/test_analysis_llm.py`
- `tests/test_semantic_analysis.py`
- `tests/test_semantic_cache.py`
- `tests/test_semantic_reports.py`
- `tests/test_semantic_eval_reports_v3.py`
- `tests/test_config_parity.py`
- `tests/test_doctor.py`
- `tests/test_live_llm_helpers.py`
- `tests/live/test_live_llm.py`
- `tests/test_release_script.py`
- `tests/test_release_workflow.py`
- `tests/acceptance/test_probe_full_dogfood.py`
- all request/config fixtures under `tests/acceptance/`
- `tests/performance/semantic_scale.py`

Repository-wide searches for the closed four-field set, positional request
construction, GPT-5.4 mini, temperature/seed defaults, qualification receipt,
and seven-day wording are explicit completion gates.

## Verification And Gates

Run in this order and record the observed result:

1. Focused red/green tests for settings, identity, adapter, cache, reports,
   live helpers, release, and acceptance fixtures.
2. `uv lock --check`
3. `uv run pytest tests -q -n auto --dist loadgroup -m "not live_llm and not benchmark"`
4. `env -u BACKSTITCH_LIVE_LLM uv run pytest tests/live/test_live_llm.py -q -o run_live_llm=false`
5. `uv run --frozen --no-sync ruff check . bin/check-doc-paths bin/check-dom15-fixtures bin/coalesce-check`
6. `uv run --frozen --no-sync python bin/ruff_suppression_index.py --check`
7. `uv run ruff format --check backstitch bin .github/scripts tests`
8. `uv run mypy backstitch bin/release.py tests --config-file pyproject.toml`
9. `uv run pytest tests/acceptance -q`
10. `uv run backstitch check --repo-root . --show-suppressions`
11. `uv run backstitch check --repo-root .`
12. The protected bounded live-qualification command owned by `bin/release.py`
    with real provider credentials.
13. The repository release dry-run or precheck path that includes the same
    live command.
14. Post-push CI: full Linux and macOS tests plus Linux, macOS, and Windows
    binary-wheel jobs. Windows is a required remote gate and a stated local
    residual until it passes.

Definition-of-done observations must include exact changed files, each command
and exit, self-corpus zero errors and warnings, suppression audit status, live
call count/cost bound, CI job links or identifiers, independent review verdict,
and final commit from `git log` if the owner authorizes landing.

## Rollout And Rollback

Rollout is one pre-release atomic activation:

1. Edit the reviewed spec delta first in the working tree, without landing a
   spec-only state.
2. Complete dependency, schema, adapter, applied config, qualification, tests,
   docs, mappings, and backlinks in the same Strategy B activation.
3. Run protected live qualification.
4. Run the full local gates and cross-platform CI.
5. Only then treat Luna as the release default.

Rollback is a normal source revert:

- revert the applied descriptor to GPT-5.4 mini;
- restore its compatible request fields and four-field code only by reverting
  the complete spec/implementation slice, never by leaving code and spec on
  different schema shapes;
- revert the `llm` dependency and lock together if the newer runtime is the
  cause;
- keep immutable cache objects. They are content-addressed and disposable, so
  no deletion or rewrite is required;
- do not repoint or migrate evidence-stable baselines. Old valid objects remain
  usable under the identity contract that created them.

There is no data migration, one-way persistence step, or external-user
compatibility window. The project is pre-release and the current config
contract is not frozen.

## Out Of Scope

- capability schema version 2 or version-aware projection
- dual old/new configuration readers
- automatic provider capability discovery or descriptor mutation
- named inference profiles
- generic provider option maps, option registries, or a new provider port
- a committed qualification receipt, freshness database, or scheduled-age SLA
- changing evidence-stable baseline election or cache layout
- removing legacy adapter constructors
- changing prompt text, semantic classifications, policy authority, packet
  schema, result schema, report schema, evaluation corpus, or search epoch
- strict-true patching through private `llm` or OpenAI methods
- expanding the supported reasoning vocabulary beyond `llm` 0.33's reviewed
  values
- Windows-specific production code without a failing Windows CI proof

## Independent Review Loop

Plan review is mandatory before T1. The reviewer receives:

- this complete plan;
- governing spec sections;
- current config, identity, adapter, cache/report, live, release, dependency,
  and CI owners;
- the user decisions in `Decisions And Scope Boundary`;
- the live and local probe observations in `Baseline And Observed Facts`.

The review must return PASS or BLOCKED and check:

- the spec delta is exact enough to promote without rediscovery;
- one-schema and optional-absence semantics are internally consistent;
- the Luna and GPT-5.5 request shapes are provider-compatible;
- evidence-stable reuse is not confused with model qualification;
- no receipt artifact is implied after removing the age rule;
- every closed reader and fixture family is inventoried;
- the hermetic proof keeps the real adapter and normalizer;
- release and Windows gates are enforceable;
- rollback preserves immutable evidence and keeps spec/code aligned.

After implementation, a fresh reviewer repeats the pass over the final diff,
verification evidence, and deviations. Larger implementation slices receive
an independent review at the identity/config boundary and again after the
adapter/qualification boundary.

## Fresh-Eyes Review

Before implementation starts, a zero-context engineer should be able to answer
from this plan alone:

1. Which request values are configured, absent, identity-bearing, and sent for
   Luna and GPT-5.5?
2. Why is wrapper introspection insufficient capability authority?
3. Why does Responses use `max_output_tokens` without renaming Backstitch's
   public `max_tokens` key?
4. Why is `strict = false` safe only as a generation constraint?
5. Which changes may re-key semantic evidence, and which events explicitly do
   not?
6. What real boundary may be faked in the hermetic wire test?
7. What proves Windows compatibility when the implementer has no Windows host?
8. How is the change reverted without deleting or rewriting cache objects?

If any answer requires unstated repository knowledge, revise the plan before
T1.

## Deviation Log

- 2026-08-23: the first protected qualification attempt exposed that the
  existing OpenAI live fixture combined `packets --kind section` with
  `--report`, while the public CLI permits packet reports only for `--kind
  all`. The final OpenAI lane now preflights its one section packet, then uses
  the public current-repository `analyze --repo-root` path to publish the exact
  packet/report pair used for immutable replay. Its aligned tiny corpus has one
  section obligation and no unrelated suppression obligation. The local lane
  retains its historical curated-packet path.
- 2026-08-23: independent review proved that OpenAI SDK default retries could
  turn one logical provider call into three wire attempts on retryable errors.
  The Responses adapter now clones the client with `max_retries = 0`, fails
  closed if that policy cannot be installed, and has a real installed-adapter
  503 test proving exactly one POST. [SC-10] and [SEM-9] now state that the
  call/cost ceilings bound remote wire attempts. This hardens the approved
  bound; it does not change model identity, request values, or call ceilings.
- 2026-08-23: the committed `SUP-AT-PRIMER-META` declaration and governed
  suppression were already present at the plan baseline, but the exact
  self-corpus test had no corresponding count or validation branch. The test
  baseline was repaired without adding or widening a production suppression.
  New [SC-10] firing tests account for the separate test-citation and Ruff
  textual-`noqa` count increments.
- 2026-08-23: the then-present external Weft corpus gate detected drift at
  sibling Weft HEAD `f5e90e413ede5f2538e4921c3b35304705549b7f`, both from a clean
  archive and from the working checkout. That observation remains historical;
  Backstitch no longer owns or conditionally runs Weft's mutable debt baseline
  (see the 2026-09-14 v0.4.0 release-readiness plan).

## Review Log

- 2026-08-23: independent pre-implementation review PASS after revisions.
  Blocking review findings resolved in the plan:
  - named Strategy B atomic activation for already-active mapped sections;
  - applied `hide_reasoning = true` to every selected Responses model;
  - defined qualification outcome categories, messages, and release exits;
  - isolated the OpenAI two-descriptor branch from the existing local prewarm
    and contract lane;
  - admitted the local lane's mandatory schema/dependency/adapter identity
    migration while preserving its operational behavior.

  Residual risks accepted for implementation verification:
  - Windows remains a required remote CI proof;
  - live provider drift or unavailability blocks release;
  - qualification audit history is process/log evidence, not a persisted
    Backstitch artifact;
  - `strict = false` may increase locally rejected generations without
    weakening normalization;
  - inherited optional request values cannot be deleted through `extend`;
  - the local live lane may re-key under the global schema and adapter change.

- 2026-08-23: independent implementation reviews initially BLOCKED on four
  concrete issues: absent optional values rendered as JSON nulls, unhashable
  reasoning values escaping as `TypeError`, SDK transport retries weakening
  the wire-attempt ceiling, and invalid qualification selections escaping the
  bounded outcome classifier. Follow-up review also caught doctor wording that
  overstated wrapper introspection and incomplete categorization of adapter
  serialization failures. The implementation now omits absent request leaves
  from config JSON, validates all reasoning types, disables and tests SDK
  retries, returns bounded selection/setup outcomes, prefixes adapter
  incompatibilities for stable classification, and states that doctor proves
  wrapper serialization only. Focused re-reviews returned PASS with no
  remaining implementation finding.

## Execution And Verification Log

- 2026-08-23: implemented T1 through T7 as one Strategy B activation against
  baseline HEAD `a28b66fb74adc34b01d3fab402b0bb871ec80b6b`. The dependency lock
  resolves `llm` 0.33, OpenAI 3.3.1, and
  the coherent HTTPX 2 graph. The applied descriptor is stable/raw GPT-5.6
  Luna with max reasoning, 16,384 logical output tokens, absent temperature
  and seed, capability schema 1 with five children, and adapter version 4.
- Focused settings, identity, adapter, cache/report, live-helper, release, and
  acceptance migrations passed. The final broad focused command over adapter,
  settings, identity, config parity, live helper, and release owners exited 0;
  the later provider/live/corpus correction suite also exited 0.
- `uv lock --check`: exit 0; 53 packages resolved.
- `uv run pytest tests -q -n auto --dist loadgroup -m "not live_llm and not benchmark"`:
  every Backstitch-owned test and the isolated full dogfood probe passed. The
  command exits 1 only at
  `test_weft_corpus_error_debt_is_exactly_the_known_set`, which correctly
  reports the external sibling-corpus drift recorded above. Running that gate
  against a clean archive of the sibling's current HEAD reproduces the same
  mismatch, so the failure is not caused by its three dirty files or by this
  implementation.
- `env -u BACKSTITCH_LIVE_LLM uv run pytest tests/live/test_live_llm.py -q -o run_live_llm=false`:
  exit 0 with one deliberate skip.
- `uv run --frozen --no-sync ruff check . bin/check-doc-paths bin/check-dom15-fixtures bin/coalesce-check`:
  exit 0.
- `uv run --frozen --no-sync python bin/ruff_suppression_index.py --check`:
  exit 0.
- `uv run ruff format --check backstitch bin .github/scripts tests`: exit 0;
  168 files formatted.
- `uv run mypy backstitch bin/release.py tests --config-file pyproject.toml`:
  exit 0; 165 source files checked.
- `uv run pytest tests/acceptance -q`: exit 0.
- `uv run backstitch check --repo-root . --format json --show-suppressions`:
  exit 0; 128 spec sections, 587 code refs, 421 mappings, 9 invariants, zero
  errors/warnings/infos, 274 suppressed issues, and zero blank reasons or
  rationales.
- `uv run backstitch check --repo-root . --format json`: exit 0 with the same
  zero-error/warning/info summary.
- Protected OpenAI qualification:
  `BACKSTITCH_LIVE_LLM=1 BACKSTITCH_LIVE_LLM_KIND=openai PYTEST_ADDOPTS='-x --maxfail=1' uv run pytest tests/live/test_live_llm.py -q -s`
  exited 0. Exact Luna and GPT-5.5 selections each made one accepted wire
  attempt, each immediate immutable replay made zero provider calls, and the
  event passed the hard $0.10 preflight ceiling. No receipt or timestamp
  artifact was written.
- `uv run python bin/release.py --dry-run --version 0.3.1`: exit 0. The dry run
  includes the exact protected OpenAI command, the separate local lane, full
  hermetic/benchmark/static/self-corpus prechecks, and performs no writes.
- Independent boundary and final implementation re-reviews: PASS after the
  corrections recorded above.
- Not available locally: Linux/macOS/Windows post-push CI. Windows remains the
  required remote portability gate. Keep the plan and index active until the
  remote matrix supplies that evidence.

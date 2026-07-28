# Deterministic-Enough Semantic CI Gate Plan

Status: report-only implementation and an authorized local cold baseline are
complete. The manual trusted refresh workflow is implemented. Promotion is
blocked by seven undispositioned dogfood candidates and an eval quality miss:
both trials missed the critical trace-removal mutation. Required CI replay,
semantic error authority, and measured thresholds remain inactive. Final
post-live independent review and completion gates pass for report-only use;
all work is uncommitted.
Plan type: implementation with spec revision.
Class: 5 (spec-changing), with class-4 hardening required because the change
alters CLI and configuration contracts, persistence, provider traffic, and
rollout sequencing.
Risk level: high and boundary-crossing. The work changes public artifacts,
configuration, exit codes, persistence, provider traffic, and CI/release policy.

## Goal

Make `backstitch analyze` deterministic enough to be a real policy-driven CI
gate, then dogfood it on Backstitch. Engineer determinism through replayable
evidence, immutable content-addressed verdicts, asymmetric failure authority,
and a measured mutation/negative-control corpus rather than claiming the model
itself is deterministic.

## Source Documents

- `docs/specs/02-backstitch-core.md` [SC-5], [SC-6], [SC-7], [SC-8], [SC-10], [SC-13], [SC-15]
- `docs/specs/03-backstitch-configuration.md` [CFG-3], [CFG-5], [CFG-6], [CFG-8], [CFG-9]
- `docs/specs/05-backstitch-invariants.md` [INV-5], [INV-7], [INV-9]
- `docs/plans/2026-07-11-deterministic-semantic-gate-spec-draft.md`
- `docs/plans/2026-07-14-deterministic-semantic-gate-corrective-spec-draft.md`
- `docs/implementation/04-backstitch-style-traceability.md`
- `.github/workflows/ci.yml`
- `.github/workflows/local-llm.yml`

## Requested Outcomes

- Uniform cache-safe packet identity for section and invariant analysis.
- Policy-neutral, immutable, auditable cached verdicts.
- Evidence-bound semantic diagnostic records with stable codes.
- Packaged default semantic policy remains advisory.
- Backstitch's applied TOML policy may promote named findings to CI errors.
- All non-secret model, cache, completeness, policy, budget, and eval controls
  are settable and set in TOML for the dogfood lane.
- `analyze` returns `0` for a complete allowed review, `1` for policy-failing
  target findings, and `2` for incomplete/tool/cache/provider failures.
- A seeded production-path mutation and negative-control corpus measures
  packet capture, recall, and false positives per model/prompt/request version.
- Backstitch starts with report-only dogfood, then activates the hard gate only
  after the measured promotion threshold is satisfied.

## Spec Baseline And Promotion

- Baseline commit: `c21d7c8bfdd0dae89ffab8d03cec0529f089f492`.
- Governing committed specs: core, configuration, and invariants at that SHA.
- Worktree state at planning time contains unrelated user-owned Codecov edits
  in `.github/workflows/ci.yml`, `README.md`, `pyproject.toml`, and
  `tests/test_release_workflow.py`, plus `.codecov.yml` and its plan. Preserve
  them.
- Exact new contract draft:
  `docs/plans/2026-07-11-deterministic-semantic-gate-spec-draft.md`.
- Promotion strategy: **A, active text first**. After independent review, add
  `docs/specs/06-semantic-gates.md` without implementation mappings, revise the
  contradictory [SC-5]/[SC-7]/[SC-10]/[INV-5]/[CFG-6] text, and record the
  worktree promotion baseline. Later slices add mappings and reciprocal code
  backlinks together.
- Promotion baseline: proposed `docs/specs/06-semantic-gates.md` SHA-256
  `d0d984ea6f361f8b7e022a0d05cd9b46d789b13e052b6fe8a35dda482eba42e3`,
  promoted in the planning worktree before implementation mappings.
  `pyproject.toml` classifies it with `planned_spec_globs` until code mappings
  and firing tests land. An exact per-file `SPEC_SECTION_UNMAPPED` suppression
  keeps the planned debt auditable under `--show-suppressions`; slice 8 removes
  both controls when reciprocal mappings exist. Active specs do not claim
  nonexistent implementation.
- Corrective promotion strategy: **A, active text first**. The exact corrective
  delta is the 2026-07-14 draft. It must receive independent blocker review,
  then replace [SEM-3] through [SEM-9] and the named SC/CFG/INV text before any
  production code changes. Record a new worktree SHA-256 promotion baseline;
  the existing planned classification/suppression remains until reciprocal
  implementation mappings and firing tests land.
- Corrective worktree promotion baseline (2026-07-14): core
  `124898b89def61daa22d51cfdb0f726b6da550e95945ab73397e37370a49bda2`,
  configuration
  `4f21053fd17e6334676bb5e250870a99c6600cdb97fbdf32f383bf3acd2beb11`,
  invariants
  `09e0a703346695bb0afca7cb5beb36f9673904e40eb6b0b7f899c6d2eb9c8ae5`,
  and semantic gates
  `6207b168d0d7574fbdb440327f871533b9bfe2e8a99dadf93fa917ca9c71ab99`.
  These hashes precede production implementation mappings.
- Post-rereview worktree baseline (2026-07-14), after the cache guard protocol
  and semantic-policy readiness corrections: core
  `7c19b7ee10d59e2d0830bd27d00e78754d8a4918cda1f8a45c45a99843981f6a`,
  configuration
  `b2a92c0d8ca2e9901ed8b6457b08a9945617d47f0f16c3d690a3c4b012e23cca`,
  invariants
  `09e0a703346695bb0afca7cb5beb36f9673904e40eb6b0b7f899c6d2eb9c8ae5`,
  semantic gates
  `ce2300fbc5feb0aba5ea6af9ef32297492dde5f741dc6f747c2ddb8f43e09e65`,
  and corrective draft
  `c89341b816ba46b3f096016487d8e0af84d681c390d5d573a5eb510eb2d94504`.

## Independent Review Record

An independent blocker review challenged ten contracts. All were incorporated
before promotion:

- hard errors now require human or mechanical verification; model-found
  evidence-bound candidates use an explicit disposition policy
- packaged semantic levels, stable codes, context-selector syntax, and later
  Backstitch rules are exact
- provider calls use single-flight locking; canonical byte stability excludes
  operational timing/counters
- backend, adapter, resolved capability path, and nonblank model revision enter
  inference identity
- exit precedence covers findings, candidates, cache/provider failures,
  warnings, budgets, and eval thresholds
- refresh precedes required replay and produces a human-reviewed patch
- TOML now includes provider/runtime/cost bounds, dispositions, refresh merge
  semantics, and Wilson interval/sample-floor controls
- the exact model-visible payload excludes derived hashes and provenance

### 2026-07-14 implementation-readiness review

The repository's preferred different-family Claude review path passed its
liveness probe but stalled because the documented `--permission-mode plan`
entered Plan Mode, wrote outside the repository, and could not exit. The
failure is recorded in `docs/implementation/03-agent-inventory.md`; it is not
review evidence. A separate same-family read-only reviewer was used as the
required fallback and returned `BLOCKED` with the findings below. Each finding
was reproduced against the current spec and code before disposition.

| Finding | Disposition | Required correction before code |
|---------|-------------|---------------------------------|
| [P1] [SEM-5]/[SEM-6] both forbids and permits evidence-bound errors | Accepted | Make candidate-error promotion a configuration error; only exact human/mechanical states may become errors |
| [P1] Pre-call identity depends on post-construction/post-response provider facts | Accepted | Define an offline provider descriptor; observed provider values are provenance-only |
| [P1] Evidence roles are undefined for several classifications | Accepted | Add an exact kind/classification role matrix and invariant declaration evidence |
| [P1] `finding_hash` depends on an undefined canonical claim | Accepted | Hash only named structured fields and trusted evidence; presentation prose is excluded |
| [P1] Packet objects collide on prompt-only changes and unknown extras can reach prompts | Accepted | Cache only the canonical semantic projection and use exact per-kind model-visible field lists |
| [P1] The old-to-new artifact transition is incomplete | Accepted | Add schema versions and enumerate producer plus read-only legacy forms |
| [P1] `summarize-analysis` cannot assert trusted evidence without packets | Accepted | Keep it presentation-only; malformed input exits `2`; it never applies gate authority |
| [P1] Lock abandonment and cleanup have no state machine | Accepted | Define exclusive-create locks, no stealing, timeout behavior, and an audited cleanup command |
| [P1] Model revision, cost, timeout, and refresh override semantics are incomplete | Accepted | Define mode-specific validity, configured conservative cost rates, timeout ownership, and an exact refresh allowlist |
| [P1] The evaluation slice has no families, command, schemas, or formulas | Accepted | Add a versioned corpus/report contract, stable first-family inventory, and public eval command |
| [P2] Stateful JSON fallback creates multiple events under one key | Accepted | Resolve one request mode before the key; provider rejection is exit `2` with no fallback call |
| [P2] Local proxy wording conflicts with provider-neutral production controls | Accepted | Proxy records/asserts configured controls and may not inject or repair them |
| [P2] Atomic publication assumes unspecified filesystem behavior | Accepted | Name the stdlib hard-link/no-replace algorithm and supported local-filesystem semantics |

Verdict: `BLOCKED`. The next slice is a reviewed spec revision, not production
code. After its exact text is reviewed and promoted, the review verdict is
rerun against the revised contract.

### 2026-07-14 corrective-contract rereview

Repeated read-only review closed dual prompt ownership, partial lock
publication, unkeyed request-path software, undefined cache-off identity,
report/debt schemas, output-failure ownership, eval hash/replay aggregation,
config ranges/defaults, threshold bindings, wildcard failure authority, and
legacy normalization. The final corrective-draft review returned `PASS`: no
remaining P1 blocker. Promotion review then found that [SC-7] had dropped the
exact newline/fsync/publication-order contract and [SC-13] had narrowed the
early-rejection side-effect boundary. Both omissions were restored from the
reviewed draft. The exact contract was then promoted into SEM/SC/CFG/INV; the
self-corpus gate returned exit `0` with zero errors, warnings, and infos.

Promotion verification on 2026-07-14:

- `git diff --check`: exit `0`.
- `uv run backstitch check --repo-root .`: exit `0`; 92 sections, 152
  mappings, 272 code refs, 502 edges, 3 invariants, 3 binds, and zero issues.
- `uv run pytest tests/test_settings.py tests/test_backstitch_corpus_traceability.py tests/acceptance/test_probe_committed_config.py -q`:
  50 tests passed.

The slice-5 policy/readiness rereview then challenged report derivability,
exact public request/run ownership, empty JSONL framing, policy winner
provenance, candidate visibility, cost-budget safety, failure-stage mapping,
and result/report path aliasing. The active specs and corrective draft now
require the exact packet-file digest, independently recomputable report fields,
closed request/run records, zero-byte empty JSONL, source-layer rule identity,
auditable `off` diagnostics, reviewed positive cost rates, and distinct resolved
output/report paths rejected before side effects. Final verdict: `PASS`; the
reviewer found no remaining P1 blocker in policy, budgets, problem mapping, or
exit precedence. The post-rereview hashes above are the implementation
baseline.

Fingerprint/evidence slice evidence on 2026-07-14:

- Red-green coverage added for exact v2 section and invariant packet hashes,
  code-owned prompt bytes/descriptors, legacy normalization, offline inference
  identity, closed model results, exact evidence reconstruction, required role
  sets, problem-only failures, and one-call JSON-mode rejection.
- `uv run pytest tests -q -m "not live_llm"`: exit `0` after correcting one
  stale mixed-version acceptance fixture.
- Focused Ruff check and format check: exit `0`.
- Focused mypy over the six changed semantic source modules: exit `0`.
- `uv run backstitch check --repo-root .`: exit `0`; zero errors, warnings,
  and infos. Planned SEM mapping debt remains explicit under the existing
  promotion suppression until the full implementation lands.
- Initial independent slice review found six contract defects: production
  identity used the controlled-test descriptor, v2 presentation could not
  consume canonical results, packet bounds and declaration races were not
  closed, identity runtime values were too permissive, and the firing matrix
  was incomplete. The first rereview found five remaining defects: missing
  presentation role checks, malformed-summary exit `0`, incomplete provider
  value invariants, loose declaration spans, and impossible edge-less section
  packets. All were reproduced, fixed, and given firing tests.
- Final independent slice rereview: `PASS`; 181 focused semantic and acceptance
  tests passed. Direct adversarial probes rejected role-less v2 findings,
  malformed summaries, invalid provider identities, invalid declaration spans,
  and section packets with no owner or test edge.
- `uv run pytest --ignore=tests/live -q`: exit `0`; the full non-live suite
  passed after updating one shared test fixture that represented a section
  packet no producer can emit.
- Focused Ruff, format, and mypy checks: exit `0` after the rereview fixes.
- `uv run backstitch check --repo-root .`: exit `0`; 92 sections, 152
  mappings, 268 code refs, 498 edges, 3 invariants, 3 binds, and zero issues.
- A broad local `pytest -q` invocation unexpectedly activated the opt-in live
  OpenAI test through shell configuration. The single request was rejected
  with HTTP 400 before model output because the configured model rejects the
  exact keyed `max_tokens` request. [SEM-3] requires rejection to exit `2` and
  forbids fallback, so this is environment incompatibility rather than passing
  live evidence. Further verification excludes `tests/live` unless provider
  spend is explicitly authorized.

Immutable-cache slice evidence on 2026-07-14:

- The cache publishes exact canonical packet, result, lock, guard, and cleanup
  audit objects with hard-link no-replace semantics. Every hit recursively
  revalidates identity, provenance shape, canonical result shape, and
  packet-local evidence.
- `off`, `read-write`, and `require` fire independently. Require replay is
  byte-identical, constructs no adapter, makes zero provider calls, and does
  not create an unnecessary guard. Mixed hits and misses preserve packet order.
- Single flight uses a canonical persistent per-key guard plus process-local
  and operating-system locks. Provider calls and waiter sleeps occur outside
  the guard; result publication and owned-lock removal occur together inside
  it. Sequential owners are valid, cleanup cannot delete a reincarnated fresh
  lock, and a valid result visible by the deadline wins over guard timeout.
- Canonical UTC timestamps use fixed six-digit microseconds and `Z`. Cache-hit
  provenance equality binds adapter ID, adapter version, and keyed plugin
  version; nullable observed provider/model/usage fields remain closed,
  validated provenance rather than identity. Missing or fresh cleanup targets
  are explicit exit-`2` errors, not idempotent success.
- Cache roots are canonicalized once before cached access. Symlinks inside the
  resolved cache root are rejected; ordinary resolved ancestors such as macOS
  `/var` remain supported. Symlink loops become structured cache errors.
- Independent review found six P1 and three P2 protocol defects across the
  initial pass and rereviews. Each was reproduced with a firing test and
  fixed. Final verdict: `PASS`; 88 focused cache/adapter tests passed, including
  repeated deadline-race runs.
- `uv run pytest --ignore=tests/live -q`: exit `0`; full non-live suite passed.
  Focused Ruff, format, mypy, and `git diff --check`: exit `0`.
- `uv run backstitch check --repo-root .`: exit `0`; 92 sections, 152
  mappings, 268 code refs, 498 edges, 3 invariants, 3 binds, and zero issues.
  The suppression audit was written to `/tmp/backstitch-self-check-cache.json`.

Semantic policy, analysis-runner, and evaluation slice evidence on 2026-07-14:

- The public analysis request/run boundary now owns packet/report validation,
  aggregate call/cost/runtime budgets, immutable cache replay, policy
  projection, atomic result/report publication, and exact `0`/`1`/`2` exit
  precedence. All semantic codes and every `[analyze]` control have firing
  tests.
- The version-1 corpus contains all eight [SEM-8] positive and negative-control
  families as ordered clean/mutated pairs with closed fixture hashes,
  transformations, expected packet identities, critical labels, and gold
  evidence. The eval command uses production scan, packet, evidence, cache,
  policy, and replay paths behind a controlled hermetic provider boundary.
- Independent review proved the initial eval report summaries were insufficient
  to recompute ambiguity, attempted-row denominators, detection/gold overlap,
  hard predictions, critical invariants, flips, replay relations, and Wilson
  qualification. The active contract and implementation now use report schema
  version 2 with ordered attempted packet identities, canonical result
  signature projections, exact confidence/interval controls, cross-trial stable
  facts, and a total public self-acceptance loader.
- Adversarial rereview rejected coherent forgeries of qualification bounds,
  latency summaries, signatures, finding hashes, detection evidence, prompt
  coverage, replay markers, cache counts, and cross-trial facts. Deep JSON,
  huge integers, and huge evidence spans are bounded at the public loader.
  Final independent verdict: `PASS`; the full evaluator test module, focused
  Ruff/format/mypy, and `git diff --check` passed.
- `uv run pytest tests/acceptance -q`: exit `0`; 21 tests passed.
- `uv run pytest tests -q -m "not live_llm"`: exit `0`.
- Full Ruff check/format and mypy over 88 source files: exit `0`.
- `uv run backstitch check --repo-root . --show-suppressions`: exit `0`; 92
  sections, 182 mappings, 288 code refs, 557 edges, 3 invariants, 3 binds, and
  zero errors, warnings, or infos. All 181 suppressions were displayed.
- On 2026-07-15 the user confirmed that the repository `OPENAI_API_KEY` and
  authenticated local `llm` installation authorize provider calls. A one-call
  compatibility probe passed with request alias `gpt-4.1-mini` and exact
  observed provider model `gpt-4.1-mini-2025-04-14`; reviewed rates are
  $0.40/M input tokens and $1.60/M output tokens.
- The first local dogfood attempt exposed ambient `LLM_MODEL=gpt-5.4-mini`
  overriding the configured model while retaining its revision. Cached modes
  now reject a different nonblank override/model pair, and trusted commands
  explicitly remove `LLM_MODEL`.
- Cold dogfood exposed two packet/model interface defects before a complete
  cache existed: the model had to count evidence end lines, then could select
  nested/overlapping duplicate snippet ranges. The v3 prompt/projection now
  supplies exact maximal `evidence_regions`, removes fully contained duplicate
  snippets from the model-visible projection, and adapter v2 supplies a
  packet-derived provider schema while retaining local evidence validation.
- The final dogfood identity emitted 59 results over 958,113 prompt bytes. Its
  post-review refresh report had 45 hits, 14 misses/calls, no provider
  or normalization problems, and seven undispositioned candidates. Two
  secret-free `require` replays had 59 hits, zero misses/calls, and
  byte-identical result JSONL with SHA-256
  `5b7486d8ff3b791829237f5bf52f69ceb0cd8157ad43a216b43076bf3305c701`.
  All current objects record provider model `gpt-4.1-mini-2025-04-14` and
  adapter version 2. Current object token usage is 258,540 input and 12,987
  output tokens, which prices to approximately $0.124 at the reviewed rate;
  earlier diagnostic cold attempts crossed the provider boundary too, so
  provider billing remains the aggregate spend authority rather than this
  final-artifact figure.
- The pending dogfood candidates are missing-trace findings for `SC-10`,
  `CFG-9`, `EXC-9`, `INV-9`, `INV-10`, and `SEM-10`, plus a weak-binding
  finding for `INV.RES.1`. Their exact packet, finding, and evidence hashes are
  preserved in `.backstitch/review/analysis-report.json`. They require human
  review; this implementation does not manufacture dispositions to obtain a
  green exit.
- The first eval attempt correctly made zero provider calls but exposed that
  full-repository `minimum_packets` and `candidate_handling` were leaking into
  isolated fixtures. Eval now neutralizes those two repository controls with a
  firing production-path test.
- The two-trial cold eval then completed 32 calls in 132.094 seconds with an
  estimated cost of $0.071. Capture, complete-result rate, valid-row rate,
  evidence overlap, and precision were 1.0; negative-control FPR, ambiguous
  rate, and uncached flip rate were 0.0. Conditional and end-to-end recall were
  0.75 with a 0.4093 Wilson lower bound. Both misses were the critical
  `trace_reference_removed` case, so promotion invariant
  `every_critical_positive_detected` failed. Secret-free require replay made
  zero calls and reproduced trial digests, outcomes, qualification metrics,
  and qualification exactly.
- `.github/workflows/semantic-refresh.yml` now owns manual trusted refresh from
  the default branch, requires the repository secret, uploads review/cache
  artifacts, and never commits or pushes. It uses `repository_dispatch` rather
  than branch-selectable `workflow_dispatch`; third-party actions are pinned
  and the credential is step-scoped. The old variable-gated one-packet cloud
  CI job was removed. Normal CI remains secret-free; required semantic replay
  is not activated before review and promotion.

## Current Evidence

- New section and invariant packets use the closed v2 projection and universal
  `packet_hash`; code-owned prompt bytes and descriptors are not packet input.
- Invariant `content_hash` retains its old bounded-content meaning and remains
  distinct from the universal packet hash.
- Canonical v2 results carry packet and analysis identity plus reconstructed,
  hashed evidence excerpts. Model output cannot provide trusted fields.
- Evidence validation proves packet-locality, role coverage, and byte identity,
  not semantic entailment. The exact [SEM-5] minimum role matrix now fires in
  both model normalization and presentation validation.
- Partial provider or model failure now emits no result row and exits `2`.
  Policy-driven exit `1` remains for the later diagnostic/policy slice.
- `summarize-analysis` exits `2` and emits no summary when any result row is
  malformed.
- Immutable cache replay is policy-neutral and byte-stable. Cache corruption,
  stale identity/provenance, lock timeout, and provider/normalization failure
  remain structured non-target problems.
- Semantic diagnostics retain default/effective policy provenance; candidates
  cannot gain hard-error authority without the exact verification state and
  applied rule required by the active contract. The unified runner enforces
  completeness and aggregate budgets before target-policy exit status.
- The measured eval corpus, CLI, Wilson metrics, qualification report, and
  schema-v2 self-acceptance boundary are implemented and hermetically verified.
- The manual cloud refresh lane is artifact-only, secret-bound, and main-only.
  It is not a required replay gate. Promotion remains blocked by the failed
  critical-positive eval invariant and pending human candidate/cache review.

## Architecture

```text
production packet generation
        |
        v
canonical packet hash + prompt/model/request/contract fingerprint
        |
        +---- cache hit ----> revalidate packet/result/evidence/provenance
        |
        +---- cache miss ---> controlled provider call ---> immutable publish
                                      |
                                      v
                         policy-neutral canonical verdict
                                      |
                                      v
                         semantic diagnostic projection
                                      |
                packaged default severity -> repo override -> fail_on
                                      |
                                 exit 0 / 1 / 2

paired clean/mutated production fixtures -> same path -> recall/precision report
```

## Required Reading And Comprehension Gate

- `backstitch/artifact_contracts.py`: why is invariant `content_hash` not a
  correct inference cache key?
- `backstitch/analysis_packets.py`: which repository populations never produce
  packets, even under `--kind all`?
- `backstitch/analysis_llm.py`: why can partial failure be green today, and
  where is evidence locality still available?
- `backstitch/analysis_results.py`: which trusted packet facts are absent when
  results are summarized later?
- `backstitch/diagnostics.py` and `backstitch/settings.py`: how do packaged
  defaults, later rules, effective severity, and `fail_on` remain separate?
- `.github/workflows/ci.yml`: why must the current PR event never receive the
  provider secret?

Do not implement until the implementer can answer all six.

## Invariants And Boundaries

- The model remains a search heuristic. Never call a model label mechanically
  or human verified.
- Evidence-bound and corroborated candidates may require disposition but are
  never policy errors. Only mechanically or human-verified findings may be
  promoted to error.
- Cache identity covers every inference-affecting input and excludes policy.
- Existing invariant `content_hash` retains its meaning; add uniform
  `packet_hash` rather than silently widening it.
- Cache entries and downloaded artifacts are untrusted. Revalidate on every
  hit through one shared evidence boundary.
- Cache objects are immutable. A new search over the same visible inputs
  requires an explicit TOML `search_epoch` change, not overwrite.
- Semantic diagnostic codes reuse the existing registry/policy engine, but do
  not enter deterministic reports or silently inherit Backstitch's broad `*`
  dogfood rule without explicit later semantic overrides.
- Classification, verification state, default severity, effective severity,
  and failure threshold remain separate structured fields.
- Packaged defaults stay advisory. Backstitch's `pyproject.toml` owns its
  stricter applied policy.
- Non-secret controls live in TOML. Provider credentials stay in provider
  secret/env storage and are never command arguments or cache content.
- `require` cache mode constructs no adapter and makes zero provider calls.
- Completeness/tool failures are exit `2`; target findings selected by applied
  policy are exit `1`.
- Canonical cached result JSONL is byte-stable under identical inputs. Run-local
  operational reports may contain duration and current counters and are not
  covered by the byte-identity promise.
- CI must report eligible/emitted population and packet coverage debt. It may
  not call `--kind all` whole-repository coverage.
- No new dependency without user approval.
- No raw model Markdown/HTML enters a privileged summary surface.
- Preserve unrelated Codecov changes and avoid drive-by refactors.

## TOML Contract

Packaged defaults add conservative keys under `[analyze]` and semantic codes to
the packaged diagnostic registry/default rules. At minimum `[analyze]` supports:

```toml
[analyze]
backend_id = "llm"
plugin_id = "repository-declared-plugin"
plugin_distribution_name = "installed-plugin-distribution"
model = "provider-model-id"
model_revision = "repository-declared-revision"
concurrency = 1
cache_path = ".backstitch/semantic-cache"
cache_mode = "off"              # off | read-write | require
search_epoch = "1"
json_mode = "prefer"            # prefer | require | off
temperature = 0.0
seed = 42
max_tokens = 512
require_complete = false
required_kinds = []
minimum_packets = 0
maximum_packets = 1000
maximum_prompt_bytes = 10000000
packet_warnings = "report"      # allow | report | error
candidate_handling = "report"   # allow | report | require_disposition
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
mode = "report"                 # report | enforce
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

Backstitch's applied `pyproject.toml` sets the reviewed model/revision,
concurrency, request controls, committed cache path, `cache_mode = "require"`,
both packet kinds, nonvacuous count/byte ceilings, complete-result requirement,
and explicit packet-warning reporting. A separate repository TOML may extend
that config and change only `cache_mode = "read-write"` for trusted refresh.

Semantic severity continues to use `[diagnostics]` ordered rules. Packaged
defaults map semantic codes to warning/info and do not make them errors.
Backstitch adds explicit semantic-family rules *after* its broad `*` rule,
promoting only human-verified or mechanically verified exact contexts.
`config show` must display both default and effective severity plus config
layers.

Evaluation model and request controls are inherited from `[analyze]`; corpus
version, trial count, mode, and thresholds live in `[analyze.eval]`. Backstitch
sets every listed key explicitly. Before a cold baseline is reviewed, it uses
the shown non-promoting sentinels with `mode = "report"`. Promotion replaces
them with measured values and `mode = "enforce"`; code must not invent a passing
threshold. Dogfood workflow YAML passes only artifact/config paths and secrets,
not duplicate non-secret policy values.

The first stable semantic codes are `SEMANTIC_CONFIRMED_MISMATCH` (`BSA001`),
`SEMANTIC_PROBABLE_MISMATCH` (`BSA002`), `SEMANTIC_MISSING_TRACE` (`BSA003`),
`SEMANTIC_WEAK_BINDING` (`BSA004`), and `SEMANTIC_AMBIGUOUS` (`BSA005`). Their
diagnostic context is the trusted verification state. Backstitch's later rules
name exact code/context pairs; the broad `*` rule is never the source of
semantic gate authority.

Before promotion, Backstitch's later `BSA* = info` rule neutralizes the broad
wildcard. After promotion, only `human_verified` and `mechanically_verified`
exact contexts may become errors. Evidence-bound candidates instead use the
TOML `candidate_handling` rule; Backstitch sets it to `require_disposition` so a
new candidate cannot silently pass or masquerade as a target error.

Exact dispositions are `[[analyze.dispositions]]` entries containing code,
packet ID, packet hash, finding hash, accepted/rejected status, and a nonblank
reason. The trusted refresh file is `.backstitch-refresh.toml`, uses
`extend = "pyproject.toml"`, and may override only cache mode to `read-write`
because output and report paths remain CLI arguments. Extending a pyproject
selects its `[tool.backstitch]` table before merge.

## Persistence Lifecycle

- Authoritative dogfood objects live under a committed
  `.backstitch/semantic-cache/` directory.
- Object names are hashes; contents include schema version and recomputable
  identity.
- A per-analysis-key single-flight lock is acquired before provider traffic.
  Waiters never call the model; abandoned locks exit `2` and require audited
  cleanup. Writes are temp + fsync + exclusive/atomic publish. Temp files are
  removed on failure; existing objects are never replaced.
- A cache refresh is explicit and trusted. The initial implementation may
  produce a patch/artifact for human commit rather than grant CI write access.
- Stale historical objects remain auditable. Pruning is explicit, never part of
  ordinary analysis, and is out of the first implementation unless cache size
  proves it necessary.
- Actions cache is acceleration only, never authority.

## Rollout, Rollback, And One-Way Doors

Rollout rungs:

1. artifact/fingerprint and cache code with policy still advisory
2. report-only committed-cache replay on Backstitch
3. cold eval baseline and reviewed thresholds
4. trusted refresh artifact plus human cache/disposition review
5. Backstitch-applied semantic errors and required replay on main/release
6. pre-merge two-stage gate only under a separate threat-model review

Rollback demotes semantic codes or clears semantic levels from `fail_on` in
Backstitch's applied TOML while retaining cached evidence and metrics. If the
cache/provenance path is faulty, set applied cache mode to `off` and disable the
semantic CI job; hermetic deterministic CI remains intact. No data migration or
destructive door is required.

The one-way risk is false authority: once a model label is presented as proven,
trust is hard to recover. UI/docs must use `evidence-bound`, not `verified`,
until an independent verification producer exists.

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|
| DOM-5 / promotion | Promote active SEM text before mappings | Promoted as Proposed and planned, with one exact auditable unmapped-section suppression | Backstitch's applied all-error policy correctly rejected active unmapped sections; claiming future modules as mappings would be false | Remove planned classification and suppression atomically with implementation mappings |
| SEM-3 through SEM-9; SC-5/6/7/10/13/15; CFG-3/6/8/9; INV-5/7/9 | Implement the promoted draft directly | Implementation-readiness review found contradictory authority and undefined identity, evidence, report, cache-recovery, budget, and evaluation contracts | Implementing those gaps would silently invent public behavior and violate the recorded baseline | Corrective delta reviewed `PASS` and promoted; closed |
| SC-6 / INV-5 legacy multiline invariant normalization | Set `end_line` from the statement line count | The reviewed one-line span contradicted [SEM-5] whenever an accepted legacy statement contained multiple lines | Keeping `end_line = line` would make the normalized v2 declaration internally invalid | Corrective draft and active SC/INV text aligned before loader implementation; independent rereview required |
| SEM-4 cleanup read/unlink race | Serialize analysis-lock mutation with a canonical per-key OS/process guard | Two cleanup processes plus a new analyzer could otherwise delete a fresh reincarnated lock after validating the old inode | Another pathname read cannot make unlink conditional; an unenforced "no concurrency" precondition would leave an admin footgun | Active SEM-4 and corrective draft amended; guarded implementation and concurrent firing tests independently reviewed `PASS` |
| SEM-8 eval report schema | Publish the corrective draft's version-1 summary records | Independent implementation review proved summary counts and opaque digests could not support [SC-13] self-acceptance or recompute promotion-critical metrics/invariants | Trusting ambiguity, attempted rows, detection, criticality, flips, and confidence from the same summaries being checked would permit coherent false qualification | Active SEM-8 and implementation use schema version 2 with detailed attempted/result facts, exact Wilson controls, derivation tests, and independent rereview `PASS` |

## Execution Evidence

- Independent blocker review: ten contract findings incorporated before spec
  promotion; see the review record above.
- `uv run backstitch check --repo-root . --show-suppressions`: exit `0`, zero
  errors, warnings, and infos. The ten planned SEM mapping debts are visible as
  exact `config_file` suppressions.
- `uv run pytest tests/test_settings.py tests/test_backstitch_corpus_traceability.py tests/acceptance/test_probe_committed_config.py -q`:
  50 passed.
- `git diff --check`: exit `0`.
- 2026-07-14 different-family review attempt: Claude liveness passed, gating
  invocation timed out after 540 seconds with no usable response. Diagnosis
  found Plan Mode wrote `~/.claude/plans/you-are-reviewing-do-eager-mitten.md`
  and could not access `ExitPlanMode`; repository files were unchanged.
- 2026-07-14 fallback implementation-readiness review: `BLOCKED` with thirteen
  reproduced findings; dispositions are recorded above.
- 2026-07-14 fingerprint/evidence independent review: two review rounds found
  eleven total contract defects; all were reproduced and closed. Final verdict
  `PASS`, with 181 focused semantic and acceptance tests passing.
- 2026-07-14 immutable-cache independent review: six P1 and three P2 defects
  were reproduced and closed across review rounds. Final verdict `PASS`, with
  88 focused cache/adapter tests passing and the full non-live suite green.
- 2026-07-14 semantic policy/runner/eval implementation: every eval manifest,
  config, CLI, runtime budget, report shape, and qualification branch has a
  firing test. Adversarial eval-report review found and closed the schema-v1
  derivability gap plus coherent forgery, numerical tolerance, unsafe-path,
  replay/cache relation, and loader-totality defects. Final verdict `PASS`.
- Final non-live verification after the rereview: acceptance 21 passed; full
  non-live pytest exit `0`; Ruff and format exit `0`; full mypy over 88 files
  exit `0`; self-corpus exit `0` with 92 sections, 182 mappings, 288 code refs,
  557 edges, and zero issues; `git diff --check` exit `0`.
- 2026-07-15 authorized local rollout: exact model compatibility passed;
  dogfood converged to 59 complete current results and zero-call byte-identical
  replay; cold eval and zero-call eval replay passed their artifact validators.
  The measured eval missed the critical trace-removal mutation in both trials,
  and seven dogfood candidates remain undispositioned. This evidence blocks
  threshold/error/required-replay promotion. Manual trusted refresh is wired;
  post-live independent review passed for report-only rollout after closing its
  workflow-secret, manifest-authority, evidence-projection, and output-alias
  findings. Final non-live, acceptance, static, and self-corpus gates pass.

## Implementation Slices

1. **Independent plan/spec review.** Review this plan and the exact SEM draft
   against current artifact, evidence, config, CLI, and CI code. Block on any
   ambiguous cache identity, policy/default conflation, or unsupported truth
   claim.

2. **Spec-promotion slice.** Add `docs/specs/06-semantic-gates.md`; update the
   specs index and reconcile [SC-5], [SC-6], [SC-7], [SC-10], [CFG-3], [CFG-6],
   [CFG-8], [CFG-9], [INV-5], [INV-7], and [INV-9]. Add related-plan backlinks.
   Record the promotion baseline. Run self-corpus before code backlinks exist;
   only info-level unmapped debt is acceptable.

3. **Uniform fingerprint and evidence slice.** Add universal `packet_hash`,
   prompt identity/version/hash, request fingerprint, analysis contract version,
   model/request provenance, exact evidence spans/excerpts/roles, and result
   schema updates. Preserve invariant `content_hash`. Update every producer and
   consumer atomically and add the acceptance compatibility probes first.
   Independent review after this slice.

4. **Immutable cache slice.** Add one cohesive cache module with schema,
   content-addressed paths, atomic publication, conflict handling, trust
   revalidation, and off/read-write/require modes. Integrate hits/misses into
   packet-order-preserving analysis. Add race, corruption, invalidation, and
   zero-call replay tests. Independent review after this slice.

5. **Semantic diagnostic and applied-policy slice.** Allocate stable semantic
   codes, project canonical verdicts into semantic diagnostic records, extend
   TOML/settings/config-show, apply packaged then repository policy, enforce
   completeness/budgets, and implement the 0/1/2 exit truth table. Add explicit
   Backstitch semantic overrides after the broad wildcard. Keep the dogfood rule
   report-only until eval promotion. Independent review after this slice.

6. **Evaluation corpus slice.** Add paired clean/mutated fixture projects and a
   live/cached eval harness that separately measures capture, conditional
   recall, end-to-end recall, validity, evidence overlap, precision/FPR,
   abstention, flip rate, replay stability, cost, and latency. Seed the exact
   mutation families from the SEM draft plus prompt-injection negative controls.
   Generate fixtures through production paths. Do not expose gold labels to the
   model.

7. **Dogfood cache and CI slice.** Populate the first cache using the configured
   cloud model in a trusted refresh context, commit reviewed cache objects,
   record the cold eval baseline, then set reviewed Backstitch-applied thresholds
   and semantic error rules. Replace the disabled one-packet lane with actual
   `packets --kind all` + `analyze`; the required replay gate uses `require`
   mode and zero provider calls. A separate trusted refresh uses the repository
   refresh TOML and `OPENAI_API_KEY`, never an Actions activation variable.
   Missing refresh credentials or incomplete required analysis fails, not skips.

8. **Packet-quality and traceability reconciliation.** Report current warning/
   omission coverage honestly. Fix packet construction only where eval shows a
   real capture failure; do not merely raise caps. Update README, repository map,
   implementation rationale (including reversal of "hash is not a cache key"),
   config docs, lessons if durable, mappings/backlinks, and plan evidence.

9. **Final gates and independent review.** Run all gates below, repeat cached
   replay to prove zero calls/byte stability, inspect the real CI summary, and
   have a fresh reviewer challenge false authority, cache trust, config layering,
   eval statistics, and secret boundaries. Resolve every finding.

## Testing And Acceptance Plan

Use red-green tests per slice. Core artifact/cache/policy tests use no model.
Only the cold eval/dogfood refresh crosses the provider boundary.

Required firing matrix:

- every model-visible semantic-projection field affects `packet_hash`;
  code-owned prompt instructions instead affect prompt identity and
  `analysis_key`
- every prompt/model/request/contract/search-epoch field affects analysis key
- policy/render/concurrency/output changes do not affect analysis key
- cache hit makes zero calls; one changed packet makes exactly one call
- mixed hit/miss output remains packet ordered and byte-stable
- corrupt/stale/conflicting cache objects and invalid evidence exit `2`
- every semantic code fires with default/effective severity visible
- packaged policy remains advisory; Backstitch applied policy changes cached
  exit behavior without a model call
- complete allowed review exits `0`; selected target finding exits `1`;
  incomplete/provider/cache/config failure exits `2`
- empty, partial, duplicate, over-count, over-byte, missing-kind, and warning
  policy cases all fire
- actionable verdicts reject empty/one-sided/mismatched evidence
- dispositions are exact and auditable
- every TOML key changes observable behavior or config output
- `--no-config` proves packaged behavior differs from applied dogfood behavior
- mutation capture and judge recall are measured separately
- labelled clean controls measure precision/FPR
- repeated uncached trials report flip rate; cached replay is byte-identical
- CI gate and refresh paths prove secret/ref/config/cache boundaries
- [SC-10] acceptance suite stays green and gains black-box semantic cache/policy
  probes

## Verification Commands

Exact focused commands will be added per slice. Final minimum:

```bash
uv run pytest tests/acceptance -q
uv run pytest tests -q -m "not live_llm"
uv run ruff check .
uv run ruff format --check backstitch bin .github/scripts tests
uv run mypy backstitch bin/release.py .github/scripts tests --config-file pyproject.toml
uv run backstitch check --repo-root . --show-suppressions
```

Live/cached final gates:

```bash
# trusted cold population/eval, only when explicitly authorized to spend
OPENAI_API_KEY=... backstitch --config .backstitch-refresh.toml analyze ...

# deterministic required replay: no provider key, zero model calls
backstitch --config pyproject.toml analyze ...
```

Completion requires the default self-corpus command to exit `0` with zero
errors/warnings, all suppressions auditable, all SEM contract elements firing,
the acceptance suite passing, the cold metrics recorded, and a second cache
replay byte-identical with zero provider calls.

## Independent Review Loop

Reviewer receives the exact SEM draft, this plan, governing specs, artifact/
packet/result/adapter/settings/diagnostics code, workflows, current dogfood
counts, and each slice's tests/evidence.

Prompt:

> Review this as a high-risk semantic CI-gate contract. Look for any place the
> design confuses evidence locality with truth, cache replay with correctness,
> packaged defaults with Backstitch's applied policy, target findings with tool
> failures, recall with precision, or `--kind all` with whole-repository
> coverage. Challenge cache identity, immutability, race handling, config
> layering, exit codes, mutation validity, secret boundaries, and rollback.
> Could you implement it confidently and correctly against the draft as if
> promoted?

Each point is accepted/incorporated, rejected with evidence, or marked out of
scope with reasoning. Run review after the plan, fingerprint/evidence slice,
cache slice, policy slice, dogfood slice, and final diff.

## Out Of Scope

- Claiming general semantic entailment is mechanically proven.
- Automatic fixes.
- Executing PR-controlled code with provider secrets.
- Pre-merge privileged analysis before its separate two-stage threat model.
- Using GitHub Actions cache as authoritative verdict storage.
- Automatically committing directly to `main` from CI.
- A generic mutation framework for arbitrary downstream repositories in the
  first dogfood implementation.
- Raising snippet/owner caps without measured capture evidence.
- New dependencies, providers, or storage services.
- Committing, pushing, or changing remote repository settings on the user's
  behalf.

## Fresh-Eyes Review

The pre-implementation fresh-eyes pass is complete and blocking. It found that
the promoted prose was human-readable but not agent-executable at the identity,
evidence, report, cache-recovery, and evaluation boundaries. Production work
remains stopped until an exact corrective delta is reviewed and promoted.
Re-read after each meaningful slice and record observed commands/results here
rather than treating status text as evidence.

# Deterministic-Enough Semantic Gate

Specs:

- `docs/specs/06-semantic-gates.md` [SEM-1] through [SEM-10]
- `docs/specs/07-verification-and-evidence-cases.md` [EVC-2], [EVC-3],
  [EVC-5] through [EVC-7], [EVC-9.1], [EVC-10.1], [EVC-11], and [EVC-12]

Plans:

- `docs/plans/2026-07-11-deterministic-semantic-gate-plan.md`
- `docs/plans/2026-07-15-agent-guided-evidence-cases-plan.md`
- `docs/plans/2026-07-27-semantic-analysis-lifecycle-plan.md`
- `docs/plans/2026-07-28-documented-suppression-governance-plan.md`
- `docs/plans/2026-07-29-architecture-quality-remediation-plan.md`

Backstitch turns aligned intent into an executable gate in two stages. The
deterministic stage identifies executable obligations and builds a closed,
source-derived evidence packet. The semantic stage asks an analyzer and an
optional blinded verifier whether that evidence supports the obligation. A
model performs bounded search. It does not own source truth, evidence spans,
policy authority, or exit behavior.

The implementation now uses source-aligned schema-3 section/invariant packets,
schema-4 suppression packets, packet-report schema 3, analysis-report schema 4,
and semantic-evaluation schema 3. Exact packet-report schema 2 and
analysis-report schema 3 readers remain for the immediately prior
section/invariant-only contract. Earlier artifacts remain bounded historical
validation inputs, not current producer or promotion contracts.

## Ownership And Boundaries

No component may silently acquire authority owned by another layer:

| Owner | Boundary | Required action on failure |
|---|---|---|
| `obligation_runtime.py` | One accepted repository snapshot and the obligation/readiness inventory derived from it | Fail the current operation; never rebuild only part of the inventory |
| `evidence_discovery.py` | Complete deterministic candidate catalog, graph closure, receipts, budgets, and obligation-local derivation | Fail closed on budget or catalog-authority mismatch; never truncate candidates |
| `analysis_packets.py` | Current mixed schema-3/schema-4 packet and schema-3 packet-report construction from the accepted snapshot | Publish neither artifact when required evidence, counterevidence, or an artifact byte ceiling fails |
| `packet_application.py` | Provider-free packet-command runtime, deterministic precedence, packet/report assembly, and ordered publication | Return typed failures with no partial output except the exact finals reported by the publication owner |
| `semantic_packets.py` | Canonical model-visible projection, prompt identity, and historical packet validation | Change packet or prompt identity whenever model-visible input changes |
| `semantic_identity.py` | Offline provider and request fingerprint before adapter construction | Use a new identity for any inference-affecting change |
| `semantic_verification_contract.py` | Verifier prompt metadata and cache-independent immutable claim, request, identity, and work records | Change the closed verifier contract or prompt identity whenever verifier-visible input changes; import no cache or analysis runtime |
| `analysis_llm.py` | Provider request construction and wire adaptation | Preserve the logical request identity; reject unsupported or malformed provider behavior |
| `analysis_results.py` and `semantic_evidence.py` | Closed output normalization and packet-local evidence reconstruction | Reject malformed output; never repair JSON or widen evidence |
| `semantic_cache.py` | Immutable untrusted cache, shared analyzer/review/verifier ownership coordination, and audited lock cleanup | Treat corrupt, stale, conflicting, or incomplete objects as exit `2`; keep cache state disposable and non-authoritative |
| `semantic_verification.py` | Blinded adversarial verification over a reason-free claim projection | Keep the verifier result evidence-bound and replayable; model identity need not differ from the analyzer |
| `semantic_policy.py` | Stable diagnostics, exact selectors, dispositions, and effective policy | Keep findings advisory unless an allowed verification state and qualification grant authority |
| `semantic_budget.py` | Shared positive-cost contract, exact per-request ceiling arithmetic, and provider/cache-free cold analyzer projection | Never read cache state, rebuild request bytes, project verifier work before findings, or supply a provider price |
| `semantic_analysis.py` | Completeness, cache-aware execution budgets, provider/cache execution, policy projection, report bytes, historical writes, and 0/1/2 truth | Keep cache/provider and semantic-policy mechanics independent of CLI presentation; consume the shared cost owner |
| `semantic_application.py` | Current/historical input validation, current readiness and packetization, schema-2 preflight projection, semantic-run invocation, currentness recapture, and ordered current publication | Publish current artifacts only after recapture proves the accepted source image is unchanged |
| `artifact_publication.py` | Generic same-directory staging, durability, ordered replacement, and partial-publication context | Stage every final before currentness validation; clean only staging paths created by the invocation |
| `semantic_reports.py` | Ordered closed-shape phases and authoritative cross-field validation for packet and analysis sidecars | Reject unknown fields in contract order, then reject forged counts, identities, hashes, or authority at every read boundary |
| `semantic_eval_identity.py` | Closed analyze/verify effective-epoch derivation | Accept only the two named domains and bind base epoch, corpus digest, and trial with the stable one-separator encoding |
| `semantic_eval_observation.py` | Provider-free fixture materialization and source-authoritative observed facts | Derive obligations, evidence, candidates, packets, and eligibility through production deterministic owners; never trust report claims as observed facts |
| `semantic_eval.py` | Schema-3 provider execution, cache-only replay, metrics, and qualification production | Keep gold outside model requests and use the shared epoch owner for every trial |
| `semantic_eval_reports.py` | Ordered closed corpus/fixture validation, closed eval-report validation, and authoritative identity/metric recomputation | Preserve validation-phase and first-error order; recompute epoch and source-derived facts independently; reject stored values that do not match |
| `semantic-refresh.yml` | Exact trusted-main tool/config identity, disposable cache-service transfer, and fresh report retention | Restore/save only immutable cache trees; keep cache persistence failure separate from analysis |
| `semantic-pr-report.yml` and `resolve_semantic_pr.py` | Exact API-confirmed PR identity and the trusted-tool/hostile-target execution boundary | Fail closed on identity movement or unreadable heads; never install or execute target-controlled bytes |

`semantic_application.py` orchestrates the repository and historical workflows.
`cli.py` owns argument parsing, lazy provider-factory construction,
presentation, and exit mapping; it is not a second semantic pipeline.
Deterministic commands still cannot import `llm`.

Preflight budget facts follow that same ownership split. `PacketPlan` retains
the exact model-request bytes and counts. Current execution passes that
complete plan into `SemanticAnalysisRequest`; one ordered retained-byte
sequence supplies prompt and capability bounds, cost math, cache selection,
and provider dispatch for both exact-inference and evidence-stable reuse.
Missing, incomplete, reordered, or identity-mismatched current plans fail
before cache or provider work. Historical replay has no current preparation,
so it composes its ordered request bytes once from the validated historical
packets and frozen inference identities.

`semantic_budget.py` applies the same reviewed cost validation and per-request
ceiling sum used by execution. `semantic_application.py` joins those facts to
configured limits in the closed schema-2 document. The CLI only renders the
typed result; blocked text also names the selected command and config source.
The projection is conservative and cache-free: read-write overages require
cache hits, off-mode overages are exact blockers, and require mode reports its
cache dependence without inspecting cache entries. A missing packet plan
keeps the combined status `unavailable`, even when verifier work is deferred.
Verifier calls and cost otherwise remain unknown until analyzer findings own
the future verification work.

## Current Source And Packet Boundary

Current analysis begins with `backstitch analyze --repo-root PATH`. It captures
the repository, resolves obligations and reciprocal traces, runs the ordinary
deterministic check, selects executable obligations, and creates one schema-3
packet per selected obligation from that same accepted source image. Before
publication it recaptures the repository. A changed snapshot makes the run
incomplete and exits `2`.

Each packet contains:

- the exact requirement text and source coordinates;
- readiness state and source-snapshot identity;
- every required human-declared implementation or test receipt;
- the complete bounded counterevidence universe found by deterministic
  discovery;
- a trace summary, deterministic issues, and the closed evidence-coordinate
  vocabulary available to the models.

There is no warning-based truncation in the current contract. An overflow of
required text, candidate work, packet JSONL, or packet-report bytes is a hard
failure before publication. Standalone `packets --kind` filtering is useful
for inspection, but only `--kind all` can produce the complete packet report
accepted by historical replay.

Packet construction prepares one `PreparedEvidenceCatalog` per accepted
snapshot. The catalog performs the obligation-independent Python parse and
static-resolution work once. Each obligation receives cloned mutable
derivation state, so trace labels and scores cannot leak between obligations.
The catalog is bound to snapshot, profile, and discovery settings. Reuse with
different authority is rejected. Deterministic work accounting still charges
the same logical catalog visits, so the optimization changes elapsed work but
not budget truth.

Path-only declarations name the exact module candidate. They do not declare
every definition and reference in that file. Lexical seeds are bounded
implementation and test definitions, not modules, references, or issues. The
packaged default is ten seeds. These choices keep human trace authority
separate from nearby code suggested by discovery.

## Identity, Evidence, And Replay

`packet_hash` covers the exact kind-specific model-visible projection. Prompt
instructions are code-owned, so their ID, version, and byte hash enter the
analysis key separately. Provider identity, logical request controls,
contract version, and search epoch also enter that key. The current provider
adapter identity is version 3. Policy, concurrency, output paths, report
formatting do not affect inference identity. A suppression declaration,
normalized rule, matched deterministic finding, or model-visible rationale
change does affect the relevant packet identity; policy and human disposition
do not.

Parser-owned suppression-declaration lines are masked from the owning section
requirement projection while preserving line coordinates. This keeps a
suppression-only declaration or rationale edit from invalidating an otherwise
unchanged section packet; the corresponding suppression packet still rekeys.

This split permits zero-call policy replay. An inference-affecting change
misses the cache; a policy-only change reprojects the same immutable result.
Every cache hit revalidates canonical bytes, the keyed preimage, provenance,
normalization, and evidence locality. Cache objects are untrusted disposable
acceleration state. Repository defaults place them below the ignored
`.backstitch/` root; they are not ordinary source or reviewed evidence.

Each invocation recaptures current source and constructs fresh result and
report outputs from that invocation's packets, valid cache hits, live misses,
and current policy. Prior reports are never cache inputs. A failure before
publication remains an explicit exit and log event rather than a fabricated
report.

The model may return only packet ID, classification, confidence, rationale,
summary, and evidence coordinates. Backstitch reconstructs excerpts and hashes
from packet bytes, then injects packet kind, packet hash, analysis key,
verification state, diagnostic code, and provenance. Provider JSON Schema is
a generation constraint, not a trust boundary. The local normalizer remains
authoritative.

`evidence_bound` findings remain advisory. Human dispositions can produce
`human_verified`; named deterministic predicates can produce
`mechanically_verified`; a qualifying adversarial verification composition
can produce `independently_verified`. A verifier adds value through a blinded,
falsifying prompt and replayable result. A different model is optional, not a
validity requirement.

## Publication And Exit Semantics

The current runner owns one truth table:

- exit `0`: required analysis is complete and effective policy permits it;
- exit `1`: required analysis is complete and an authoritative finding has an
  effective severity in `fail_on`;
- exit `2`: configuration, source, alignment, packet, cache, provider,
  normalization, completeness, budget, qualification, publication, or
  internal failure.

Input or configuration rejection publishes nothing. Once execution is valid,
the runner atomically publishes canonical result JSONL and then its validated
analysis report. A result-publication failure may still produce a failed
report. A report-publication failure remains exit `2`.

## Evaluation And Strong-Policy Authority

The current evaluation contract is schema 3 under
`tests/semantic_eval/v3/`. `backstitch eval` uses the production capture,
obligation, discovery, packet, analyzer, verifier, cache, normalizer, and
policy paths. Gold obligations, candidates, evidence, and expected findings
stay in the harness. The authoritative validator recomputes metrics from
source-derived observed facts; it does not accept the report or gold corpus as
the observation under test.

The runner performs provider-backed primary trials followed by immediate
zero-call replay. Its report records analyzer attempts, verifier events,
evidence sufficiency, conditional and end-to-end precision/recall, false
positives, indeterminate results, uncached flips, critical-case capture,
latency, calls, and cost. Qualification is about stability and measured
precision on one content-addressed repository corpus. It does not measure
cross-model correlation or claim universal correctness.

Report mode can publish a valid report with failed checks, but it grants no
stronger policy. Enforce authority requires all of these at once:

- a reviewed, content-addressed schema-3 corpus with the required historical
  units and controls;
- at least two measured trials with the enforce thresholds, zero allowed
  false-positive rate, and all critical cases caught;
- byte-identical zero-call replay;
- an authoritative source-derived recomputation of the report;
- exact configured corpus and report paths and hashes;
- an exact independently-verified semantic-code selector.

The schema-3 qualification candidate now provides the structural corpus shape,
synthetic controls, and five [COV-7] spec-side pairs. Each pair keeps
implementation and reciprocal mapping bytes fixed while replacing an
informative contract with one of the preregistered non-informative forms. These
provider-free candidates do not establish the required 20 historical
misalignment units. Source review also found that the active analyzer prompt
classifies vague text as `ambiguous` and reserves `missing_trace` for a missing
owner, while [SEM-8] preregisters `SEMANTIC_MISSING_TRACE` for these fully
owned spec-side mutations. The Slice 8 stop condition therefore requires a
separate prompt/spec revision and requalification plan. The substantive
historical-unit count remains zero, and no reviewed provider-backed enforce
report is pinned. Current policy is report-only and has no independently
verified failure authority. This is deliberate. Repeatability without measured
precision could produce a stable rubber stamp.

## Measured Current Status

The 2026-07-16 live hosted contract passed with `gpt-5.4-mini`. It exercised
the packet-bound JSON Schema, provider request, local normalization, report
loading, evidence summary, and reload path. GPT-5 and o-family requests keep
the logical `max_tokens` identity while adapter version 3 translates it to the
wire-level `max_completion_tokens` field required by the OpenAI adapter.

The 2026-07-28 hosted contract also passed with `gpt-5.4-mini`. Its bounded
source-aligned fixture emitted one section packet and one documented
suppression packet, made two real provider calls in `read-write` mode, then
replayed byte-identical results in `require` mode with zero provider calls and
zero cache misses. The summary consumer accepted the suppression result only
when paired with the `--show-suppressions` deterministic audit.

The authorized local `llama3.2:3b` contract accepted the request and schema but
returned non-JSON text for both small obligations after roughly six minutes.
Normalization rejected both results and the run exited `2`. This proves
transport compatibility, not gate qualification. The correct response is to
use a local model that satisfies the closed output contract or qualify a
controlled transport. Backstitch must not repair the output or weaken
normalization.

The current self-repository semantic packet build also exposes a separate
scale problem. With the normal packet ceiling temporarily raised for
measurement, 51 executable obligation packets produced:

- 23,170,539 JSONL bytes;
- 23,263,716 prompt bytes;
- a largest prompt of 1,013,964 bytes.

Preparing the shared discovery catalog reduced the same build from roughly
2 minutes 48 seconds to 45.5 seconds on the development machine. The normal
10 MiB packet ceiling still rejects it, correctly. Broad whole-module human
traces create evidence and counterevidence regions that are too large for a
practical semantic gate. This is trace-precision debt, not a reason to
silently truncate the evidence packet. The deterministic self-corpus gate can
remain green while the semantic self-corpus is not yet practical.

The current repository also retains known active partial/untraced alignment
debt recorded by the evidence hardening work. Current-source analysis
therefore exits `2` at `ALIGNMENT_DEBT` before cache or provider work. Resolving
that debt is outside the suppression-governance plan; the bounded live fixture
proves the new suppression cache lifecycle without weakening readiness.

## Operator Flow

Configuration is resolved once per invocation by
`backstitch.settings.resolve_config(...)` ([CFG-5.1], [SC-5.1]). The resolver
loads packaged defaults and the selected config chain, then applies the two
defined environment inputs and one CLI layer. Command handlers receive the
resulting immutable `BackstitchSettings`; model, target-root, evaluation, and
cache code do not reread ambient Backstitch settings.

This boundary keeps tests deterministic through direct settings injection and
keeps provider-free commands structurally provider-free. An arbitrary TOML
filename is valid only when selected by `--config` or `extend`; its basename
does not grant trust or make it discoverable.

Inspect the current complete packet corpus and its closed report:

```bash
backstitch packets --repo-root . --kind all \
  --output .backstitch/packets.jsonl \
  --report .backstitch/packet-report.json
```

Run current-source analysis. This is the ordinary gate surface; it captures
and recaptures the repository itself:

```bash
backstitch analyze --repo-root . \
  --output .backstitch/analysis.jsonl \
  --report .backstitch/analysis-report.json
```

A trusted refresh selects the repository's `pyproject.toml` and applies the
reviewed runtime-only update layer:

```bash
env -u LLM_MODEL backstitch analyze --repo-root . \
  --config pyproject.toml \
  --option analyze.cache_mode read-write \
  --option verify.enabled true \
  --option verify.cache_mode read-write \
  --packets-output .backstitch/packets.jsonl \
  --packet-report-output .backstitch/packet-report.json \
  --output .backstitch/analysis.jsonl \
  --report .backstitch/analysis-report.json
```

This is the normal update flow. It reuses valid immutable hits, calls the
provider only for changed inference identities, and stores successful misses.
A policy-only change rebuilds the current report from the same raw results
without a provider call. It is available only after the addressed repository's
active obligations are executable; alignment debt correctly stops before this
cache lifecycle.

The default repository profile uses `require` for explicit zero-call replay.
Historical packet replay is also explicit and always requires its paired
packet report:

```bash
backstitch analyze \
  --packets .backstitch/packets.jsonl \
  --packet-report .backstitch/packet-report.json \
  --output .backstitch/analysis.jsonl \
  --report .backstitch/analysis-report.json
```

Any missing cache object fails with exit `2` before adapter construction. To
diagnose without cache reads or writes, use a trusted override with
`[analyze] cache_mode = "off"`. To retain a deliberate new sample, change
`[analyze] search_epoch` and, when verification is enabled,
`[verify] search_epochs`, then use `read-write`. Do not use `off` as a refresh
alias because it publishes no cache objects.

When no Backstitch process is using it, removing the whole `.backstitch/`
directory is supported. A later `read-write` invocation performs a bounded
rebuild; a `require` invocation reports misses. Fine-grained pruning and
concurrent whole-root deletion are outside the current interface.

Reports and cache objects have separate lifecycles. Reports are regenerated
run outputs and may be retained briefly as CI artifacts. The cache is an
optional, ignored accelerator and may be evicted. A durable reviewed snapshot
that survives indefinitely without a provider is not implemented; it would
need a separate authority and retention contract.

Trusted CI keeps three roots separate. The trusted tool checkout owns the
executable, locked environment, prompt, config, and cache namespace. A target
checkout supplies source bytes only. Reports live in a fresh runner-temporary
root. The trusted-main refresh binds its checkout to the dispatch run's exact
`github.sha`; it may restore and save only immutable packet/result object
trees.

The PR report workflow is manually dispatched from the default-branch
definition with an open PR number and expected lowercase full head SHA. Its
resolver checks the API's PR number, state, `main` base, exact base repository,
readable head repository, and exact head SHA before checkout. The workflow
checks out that API-confirmed SHA with credentials, submodules, and LFS
disabled, asserts both checkout identities, then repeats the API validation
immediately before analysis.

The target is never a working directory, dependency source, executable path,
import path, plugin source, hook source, or config source. Trusted Backstitch
receives it only through `--repo-root` while `--config`, cache, and output
paths remain anchored outside it. The workflow selects
`${TOOL_ROOT}/pyproject.toml` and supplies only the three literal reviewed
options above; target bytes and event payload cannot form a config path,
option key, or option value. Provider credentials are step-scoped.
Artifacts are always attempted, but a pre-publication failure remains a
workflow error and log rather than a fabricated report. This lane is
observational: it creates no comment, check, status, commit, push, disposition,
or merge authority.

Exercise the current schema-3 evaluator in non-authoritative report mode:

```bash
backstitch eval \
  --corpus tests/semantic_eval/v3/manifest.json \
  --config pyproject.toml \
  --option analyze.cache_mode read-write \
  --option verify.enabled true \
  --option verify.cache_mode read-write \
  --output .backstitch/verification-eval-report.json
```

Do not treat that output as authority merely because it is valid. A human must
review the corpus and report, choose enforce thresholds, pin both hashes, and
enable only exact selectors supported by the authoritative report.

## Verification

The implementation is covered by:

- source-snapshot, obligation-readiness, candidate-receipt, packet-schema-3,
  and report-schema-2/3 contract tests;
- prepared-catalog authority, isolation, parse-reuse, and deterministic work
  accounting tests;
- prompt, provider, request, adapter, contract, and epoch identity matrices;
- cache race, corruption, deadline, lock cleanup, and zero-call replay tests;
- analyzer/verifier malformed-output, evidence-locality, policy-authority, and
  0/1/2 exit tests;
- schema-3 corpus and report consistency plus source-authoritative metric
  recomputation tests;
- hosted and local live transport probes, whose outcomes must be recorded
  rather than assumed from configuration;
- the full non-live suite, Ruff, mypy, [SC-10] acceptance probes, and the
  deterministic self-corpus gate.

Live provider success and hermetic contract success prove different things.
Neither may replace the other. Performance qualification is currently
unavailable because no reviewed Linux runtime identity, committed runner
contract, or same-environment baseline exists. Development-machine timings do
not substitute for that separate pinned-runner contract.
